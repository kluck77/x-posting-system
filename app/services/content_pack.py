"""
콘텐츠 팩 생성기
================
단일 소스에서 구조화된 초안 묶음을 한 번의 AI 호출로 생성합니다.

출력 스키마:
  main_posts       × 3  (각도가 다른 메인 포스트)
  short_version    × 1  (짧은 버전)
  reply_drafts     × 3  (트렌드 댓글용 초안)
  quote_post_drafts × 2  (인용 포스트)
  thread_option    × 1  (선택적 스레드 시작)
  risk_flags            (위험 요소 목록)
  topic_tags            (주제 태그)
  why_it_matters        (국제 독자 관련성 1문장)
  style_warnings        (스타일/반복 경고 — 선택)

설계 원칙:
- 기존 approve 파이프라인 대체 아님 — 병렬 흐름
- AI 단일 호출 (비용 최소화)
- OpenAI 우선, Anthropic 폴백, Mock 항상 가능
"""

import json
import logging
from dataclasses import dataclass, field
from typing import Optional

from app.models.content_request import ContentRequest

logger = logging.getLogger(__name__)


# ─── 출력 스키마 ──────────────────────────────────────────────────────────────

@dataclass
class ContentPack:
    """구조화된 초안 묶음."""
    main_posts: list[str] = field(default_factory=list)        # 3개
    short_version: str = ""                                     # 1개
    reply_drafts: list[str] = field(default_factory=list)      # 3개
    quote_post_drafts: list[str] = field(default_factory=list) # 2개
    thread_option: Optional[str] = None                        # 선택
    risk_flags: list[str] = field(default_factory=list)
    topic_tags: list[str] = field(default_factory=list)
    why_it_matters: str = ""
    style_warnings: list[str] = field(default_factory=list)
    # 메타
    source_url: Optional[str] = None
    source_type: str = "news_link"

    def is_valid(self) -> bool:
        return bool(self.main_posts and self.why_it_matters)

    def topic_tags_str(self) -> str:
        return " ".join(f"#{t}" for t in self.topic_tags) if self.topic_tags else ""


# ─── 시스템 프롬프트 ──────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """You are a senior content strategist for an English-language X account (@cheesesvav) that explains Korean affairs to international readers.

Account identity:
- "Beyond headlines: how Korea really works, feels, and changes."
- NOT a translator. You provide interpretation, context, and angles that Western media misses.
- Audience: internationally curious professionals (finance, geopolitics, tech, crypto) aged 25-45.
- Voice: credible, analytical, occasionally wry. Never sensationalist, never preachy.

Your task:
Given source material, generate a structured content pack in JSON format.

Output ONLY valid JSON matching this schema exactly:
{
  "main_posts": [
    "Hook line\\n\\nBody text. Max 280 chars total.",
    "Hook line\\n\\nBody text. Max 280 chars total.",
    "Hook line\\n\\nBody text. Max 280 chars total."
  ],
  "short_version": "One punchy tweet. Max 200 chars. No explanation.",
  "reply_drafts": [
    "Reply to add context or data. Max 200 chars. Sounds like an informed bystander.",
    "Reply that challenges a common assumption. Max 200 chars.",
    "Reply sharing a related observation. Max 200 chars."
  ],
  "quote_post_drafts": [
    "Quote-tweet framing. Max 220 chars. Adds the Korean-insider angle.",
    "Quote-tweet framing. Max 220 chars. Different angle from first."
  ],
  "thread_option": "Optional: first tweet of a 4-tweet thread if the story is complex enough. null if not needed.",
  "risk_flags": ["List any sensitivity issues, e.g. 'politically charged — avoid during election cycle'"],
  "topic_tags": ["economy", "BOK", "rates"],
  "why_it_matters": "One sentence: why international readers should care about this right now.",
  "style_warnings": ["Optional: e.g. 'similar to last week chaebol post — vary the angle'"]
}

Rules for main_posts:
1. Each post must have a different angle (data-driven / human-angle / contrarian)
2. Hook must NOT start with "South Korea" or "Korea's"
3. Hook should have a number, stat, or specific name
4. No banned words: however, furthermore, moreover, it is worth noting, in conclusion
5. End with a CTA or thought-provoking question
6. Max 280 characters total (hook + body combined)

Rules for reply_drafts:
- Sound like an engaged, informed individual — not a brand account
- Add value: data, context, or genuine insight
- Max 200 chars each

Rules for risk_flags:
- Be specific. "politically sensitive" is not useful. "references 2024 martial law — verify before posting" is useful.
- Empty array [] if no significant risks."""


# ─── 생성 함수 ────────────────────────────────────────────────────────────────

async def generate_content_pack(request: ContentRequest) -> ContentPack:
    """
    ContentRequest → ContentPack.

    AI 우선순위: OpenAI → Anthropic → Mock
    실패 시 Mock 폴백 — 절대 예외 발생 안 함.

    Layer 2 (try/except 보호):
      - RepetitionGuard: 최근 승인 초안과 Jaccard 유사도 비교
      - VoiceGuard: AI 어투 패턴 감지
    두 가드 실패 시 pack 정상 반환 (style_warnings만 누락).
    """
    source_text = request.to_source_text()
    title = request.to_title()

    user_prompt = f"Source type: {request.source_type}\n"
    if request.source_url:
        user_prompt += f"URL: {request.source_url}\n"
    user_prompt += f"\nContent:\n{source_text or title}\n\nGenerate the content pack JSON now."

    raw = await _call_ai(user_prompt)

    if raw:
        pack = _parse_response(raw)
        if pack and pack.is_valid():
            pack.source_url = request.source_url
            pack.source_type = request.source_type
            logger.info(
                f"콘텐츠 팩 생성 완료: {len(pack.main_posts)} posts, "
                f"tags={pack.topic_tags}"
            )
            _apply_guards(pack)
            return pack

    logger.warning("AI 응답 파싱 실패 — Mock 팩 반환")
    pack = _mock_pack(request)
    _apply_guards(pack)
    return pack


def _apply_guards(pack: "ContentPack") -> None:
    """
    RepetitionGuard + VoiceGuard를 pack에 적용.
    실패 시 무시 (Layer 2 — style_warnings 미반영이 최악의 결과).
    """
    # VoiceGuard — DB 불필요, 항상 실행
    try:
        from app.services.voice_guard import check_pack_voices
        voice_warnings = check_pack_voices(
            pack.main_posts + [pack.short_version] + pack.reply_drafts
        )
        for w in voice_warnings:
            if w not in pack.style_warnings:
                pack.style_warnings.append(w)
    except Exception as e:
        logger.warning(f"[VoiceGuard] 실패 (무시): {e}")

    # RepetitionGuard — DB 세션 필요
    try:
        from app.db import get_db
        from app.services.repetition_guard import RepetitionGuard
        db = get_db()
        guard = RepetitionGuard(db)
        rep_warnings = guard.check_pack(pack)
        for w in rep_warnings:
            if w not in pack.style_warnings:
                pack.style_warnings.append(w)
    except Exception as e:
        logger.warning(f"[RepetitionGuard] 실패 (무시): {e}")


async def _call_ai(user_prompt: str) -> Optional[str]:
    """AI 호출. OpenAI → Anthropic → None 순서."""
    from app.config import settings

    # OpenAI 시도
    if settings.openai_api_key:
        try:
            import httpx
            async with httpx.AsyncClient(timeout=60) as client:
                r = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={"Authorization": f"Bearer {settings.openai_api_key}"},
                    json={
                        "model": "gpt-4o-mini",
                        "messages": [
                            {"role": "system", "content": _SYSTEM_PROMPT},
                            {"role": "user", "content": user_prompt},
                        ],
                        "temperature": 0.8,
                        "response_format": {"type": "json_object"},
                    },
                )
                r.raise_for_status()
                data = r.json()
                return data["choices"][0]["message"]["content"]
        except Exception as e:
            logger.warning(f"OpenAI 콘텐츠 팩 호출 실패: {e}")

    # Anthropic 시도
    if settings.anthropic_api_key:
        try:
            import httpx
            async with httpx.AsyncClient(timeout=60) as client:
                r = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "x-api-key": settings.anthropic_api_key,
                        "anthropic-version": "2023-06-01",
                    },
                    json={
                        "model": "claude-haiku-4-5-20251001",
                        "max_tokens": 2000,
                        "system": _SYSTEM_PROMPT,
                        "messages": [{"role": "user", "content": user_prompt}],
                    },
                )
                r.raise_for_status()
                data = r.json()
                return data["content"][0]["text"]
        except Exception as e:
            logger.warning(f"Anthropic 콘텐츠 팩 호출 실패: {e}")

    return None


def _parse_response(raw: str) -> Optional[ContentPack]:
    """AI 응답 JSON → ContentPack."""
    try:
        # JSON 블록 추출 (```json ... ``` 래핑 처리)
        text = raw.strip()
        if "```" in text:
            start = text.find("{")
            end = text.rfind("}") + 1
            if start != -1 and end > start:
                text = text[start:end]

        data = json.loads(text)

        return ContentPack(
            main_posts=_ensure_list(data.get("main_posts"), 3),
            short_version=str(data.get("short_version", "")),
            reply_drafts=_ensure_list(data.get("reply_drafts"), 3),
            quote_post_drafts=_ensure_list(data.get("quote_post_drafts"), 2),
            thread_option=data.get("thread_option") or None,
            risk_flags=_ensure_list(data.get("risk_flags"), None),
            topic_tags=_ensure_list(data.get("topic_tags"), None),
            why_it_matters=str(data.get("why_it_matters", "")),
            style_warnings=_ensure_list(data.get("style_warnings"), None),
        )
    except Exception as e:
        logger.warning(f"ContentPack 파싱 오류: {e}")
        return None


def _ensure_list(value, max_items: Optional[int]) -> list:
    """None / non-list → 빈 리스트. 최대 개수 제한."""
    if not isinstance(value, list):
        return []
    items = [str(v) for v in value if v]
    return items[:max_items] if max_items else items


def _mock_pack(request: ContentRequest) -> ContentPack:
    """Mock 팩 — API 키 없을 때 / 파싱 실패 시."""
    title = request.to_title()[:60]
    return ContentPack(
        main_posts=[
            f"[Mock A] {title}\n\nThis is the data-driven angle for international readers.",
            f"[Mock B] {title}\n\nThis is the human-interest angle with on-the-ground context.",
            f"[Mock C] {title}\n\nThis is the contrarian angle that challenges the Western narrative.",
        ],
        short_version=f"[Mock short] {title[:80]} — the context Western media skips.",
        reply_drafts=[
            "[Mock reply 1] Worth adding: the regulatory context here is different from what most assume.",
            "[Mock reply 2] Counter-point: the data from Q3 tells a different story.",
            "[Mock reply 3] Saw this developing for months. The signal was in the bond market.",
        ],
        quote_post_drafts=[
            f"[Mock quote 1] This is why the Korea angle matters for global markets.",
            f"[Mock quote 2] The untold part: what this means for the rest of Asia.",
        ],
        thread_option="[Mock thread] 1/ Here's what everyone is missing about this story...",
        risk_flags=["Mock mode — no real risk analysis available"],
        topic_tags=["mock", "korea", "economy"],
        why_it_matters="Mock mode: international readers care because this affects regional dynamics.",
        style_warnings=[],
        source_url=request.source_url,
        source_type=request.source_type,
    )
