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

_SYSTEM_PROMPT_KO = """당신은 한국어 X 계정(@cheesesvav)의 시니어 콘텐츠 전략가입니다.

계정 정체성:
- "헤드라인 너머: 한국이 실제로 어떻게 돌아가고, 느끼고, 변하는지."
- 단순 번역이 아님. 해석, 맥락, 주류 미디어가 놓치는 시각을 제공.
- 독자: 경제·지정학·테크·크립토에 관심 있는 25-45세 전문직.
- 어투: 신뢰감 있고, 분석적이며, 간간이 재치. 자극적이거나 설교조 금지.

작업:
주어진 소스 자료를 기반으로 구조화된 콘텐츠 팩을 JSON으로 생성하라.
**모든 출력 텍스트는 반드시 한국어로 작성하라.**

아래 스키마와 정확히 일치하는 JSON만 출력:
{
  "main_posts": [
    "훅 라인\\n\\n본문. 총 280자 이내.",
    "훅 라인\\n\\n본문. 총 280자 이내.",
    "훅 라인\\n\\n본문. 총 280자 이내."
  ],
  "short_version": "핵심만 담은 짧은 트윗. 200자 이내. 설명 없이.",
  "reply_drafts": [
    "맥락이나 데이터를 추가하는 답글. 200자 이내. 정보 있는 관찰자 어투.",
    "통념에 도전하는 답글. 200자 이내.",
    "관련 관찰을 공유하는 답글. 200자 이내."
  ],
  "quote_post_drafts": [
    "인용 트윗 프레이밍. 220자 이내. 한국 내부자 시각 추가.",
    "인용 트윗 프레이밍. 220자 이내. 첫 번째와 다른 각도."
  ],
  "thread_option": "선택: 이야기가 충분히 복잡하면 4트윗 스레드의 첫 트윗. 불필요하면 null.",
  "risk_flags": ["민감도 이슈 구체적으로. 예: '2024 계엄 언급 — 게시 전 확인 필요'"],
  "topic_tags": ["경제", "한은", "금리"],
  "why_it_matters": "한 문장: 왜 지금 이 이야기가 중요한지.",
  "style_warnings": ["선택: 예: '지난주 재벌 포스트와 유사 — 각도 변경 필요'"]
}

main_posts 규칙:
1. 각 포스트는 다른 각도 (데이터 기반 / 인간적 시각 / 반론적)
2. 훅이 "한국은" 또는 "한국의"로 시작하면 안 됨
3. 훅에 숫자, 통계, 구체적 이름 포함
4. 금지 표현: 그러나, 더욱이, 게다가, 주목할 점은, 결론적으로
5. CTA 또는 생각을 유발하는 질문으로 마무리
6. 총 280자 이내 (훅 + 본문 합산)

reply_drafts 규칙:
- 브랜드 계정이 아닌, 관심 있고 정보력 있는 개인처럼
- 데이터, 맥락, 진짜 인사이트로 가치 추가
- 각 200자 이내

risk_flags 규칙:
- 구체적으로. "정치적으로 민감"은 쓸모없음. "2024 계엄 참조 — 게시 전 검증 필요"는 유용함.
- 위험 없으면 빈 배열 []."""

_SYSTEM_PROMPT_EN = """You are a senior content strategist for an English-language X account (@cheesesvav) that explains Korean affairs to international readers.

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


def _get_system_prompt(language: str) -> str:
    """language에 따라 시스템 프롬프트 반환. 기본은 한국어."""
    if language.lower() in ("en", "english", "eng"):
        return _SYSTEM_PROMPT_EN
    return _SYSTEM_PROMPT_KO


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
    language = getattr(request, "language", "ko") or "ko"

    user_prompt = f"Source type: {request.source_type}\n"
    if request.source_url:
        user_prompt += f"URL: {request.source_url}\n"
    user_prompt += f"\nContent:\n{source_text or title}\n\n"
    if language.lower() in ("en", "english", "eng"):
        user_prompt += "Generate the content pack JSON now."
    else:
        user_prompt += "콘텐츠 팩 JSON을 생성하라. 모든 텍스트는 한국어로."

    raw = await _call_ai(user_prompt, language=language)

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


async def _call_ai(user_prompt: str, language: str = "ko") -> Optional[str]:
    """AI 호출. OpenAI → Anthropic → None 순서."""
    from app.config import settings

    system_prompt = _get_system_prompt(language)

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
                            {"role": "system", "content": system_prompt},
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
                        "system": system_prompt,
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
    language = getattr(request, "language", "ko") or "ko"

    if language.lower() in ("en", "english", "eng"):
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

    return ContentPack(
        main_posts=[
            f"[Mock A] {title}\n\n데이터 기반 시각으로 본 핵심 분석.",
            f"[Mock B] {title}\n\n현장 맥락을 담은 인간적 시각.",
            f"[Mock C] {title}\n\n통념에 도전하는 반론적 시각.",
        ],
        short_version=f"[Mock 짧은] {title[:80]} — 주류 미디어가 놓친 맥락.",
        reply_drafts=[
            "[Mock 답글 1] 추가할 점: 여기서 규제 맥락은 대부분의 예상과 다르다.",
            "[Mock 답글 2] 반론: 3분기 데이터는 다른 이야기를 한다.",
            "[Mock 답글 3] 수개월 전부터 전개 감지. 신호는 채권 시장에 있었다.",
        ],
        quote_post_drafts=[
            f"[Mock 인용 1] 이게 왜 글로벌 시장에 중요한지.",
            f"[Mock 인용 2] 알려지지 않은 부분: 아시아 전체에 미치는 의미.",
        ],
        thread_option="[Mock 스레드] 1/ 이 이야기에서 모두가 놓치고 있는 것...",
        risk_flags=["Mock 모드 — 실제 위험 분석 불가"],
        topic_tags=["mock", "한국", "경제"],
        why_it_matters="Mock 모드: 지역 역학에 영향을 미치기 때문에 중요.",
        style_warnings=[],
        source_url=request.source_url,
        source_type=request.source_type,
    )
