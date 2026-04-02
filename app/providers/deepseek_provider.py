"""
DeepSeek 프로바이더
====================
역할: DraftWriter (대안) + Reviewer (대안)

DeepSeek은 OpenAI 호환 API를 사용합니다.
강점:
  - 한국어 / 중국어 / 아시아 컨텍스트 이해 최강
  - 가격: $0.14/M input tokens (GPT-4o-mini 대비 10배 저렴)
  - deepseek-reasoner: 체인-오브-쏘트 분석 (팩트 검증 + 리뷰에 탁월)

모델:
  - deepseek-chat: 빠른 초안 작성
  - deepseek-reasoner: 심층 분석 / 리뷰어 역할
"""

import json
import logging
import re
import httpx
from app.config import settings
from app.providers.base import BaseDraftWriter, BaseReviewer, DraftResult, ReviewResult

logger = logging.getLogger(__name__)

DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"
DEEPSEEK_CHAT_MODEL     = "deepseek-chat"
DEEPSEEK_REASONER_MODEL = "deepseek-reasoner"

# DeepSeek은 같은 시스템 프롬프트를 사용 (브랜드 일관성 유지)
# openai_provider의 SYSTEM_PROMPT와 동일한 내용
_DRAFT_SYSTEM = """You are the draft writer for @cheesesvav — an anonymous English-language X account.

Account identity: "Beyond headlines: how Korea really works, feels, and changes."
Insider feel. No name. Just signal.

Use the 5-block structure:
HOOK → ONE FACT → YOUR TAKE → WHAT FOREIGNERS MISS → CLOSE + CTA

Hook types: CONTRADICTION / NUMBER SHOCK / BURIED STORY / CONTRARIAN / PERSONAL STAKE / TIMING EDGE
CTAs: "No name. Just signal. Follow to stay ahead of Korean markets." and variants.

STRICT RULES:
- NEVER start with "South Korea" or "Korea's"
- Body under 270 characters
- One opinion. No hedging. Use "you".

Respond in JSON ONLY:
{
  "hook": "...",
  "body": "... (under 270 chars)",
  "thread_continuation": null,
  "category_suggestion": "politics|policy|economy|society|crypto|kpop_culture|evergreen|community",
  "content_pillar": "economy|crypto|geopolitics|community",
  "optimal_post_time": "09:00 EST",
  "tone_notes": "hook type, opinion, angle"
}"""

_REVIEW_SYSTEM = """You are the editorial reviewer for @cheesesvav.
Account identity: "Beyond headlines: how Korea really works, feels, and changes."

Review the draft for:
1. Hook doesn't start with "South Korea"/"Korea's"
2. Specific number or contradiction in hook
3. Body under 270 characters
4. CTA present
5. Risk level: politics/economy/crypto/society → medium or high; evergreen → low

Respond in JSON ONLY:
{
  "hook": "final hook",
  "body": "final body (under 270 chars)",
  "thread_continuation": null,
  "category": "politics|policy|economy|society|crypto|kpop_culture|evergreen|community",
  "risk_level": "low|medium|high",
  "risk_reasoning": "...",
  "ai_rationale": "...",
  "recommended_action": "approve|review|reject"
}"""


async def _call_deepseek(
    system: str,
    user_msg: str,
    model: str = DEEPSEEK_CHAT_MODEL,
    api_key: str | None = None,
) -> str:
    """DeepSeek API 호출 (OpenAI 호환)."""
    key = api_key or settings.deepseek_api_key
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            DEEPSEEK_API_URL,
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_msg},
                ],
                "temperature": 0.7,
                "response_format": {"type": "json_object"},
            },
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]


def _strip_json(text: str) -> str:
    """마크다운 코드블록 JSON 래핑 제거."""
    text = re.sub(r"^```(?:json)?\s*", "", text.strip())
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


class DeepSeekDraftWriter(BaseDraftWriter):
    """DeepSeek Chat을 사용한 초안 작성기. 한국어 컨텍스트에 최적화."""

    async def generate_draft(
        self,
        title: str,
        source_text: str,
        language: str = "en",
        source_type: str = "manual",
    ) -> DraftResult:
        logger.info(f"[DeepSeek DraftWriter] 초안 생성: '{title[:50]}'")

        community_addendum = ""
        if source_type == "community_input":
            community_addendum = (
                "\n\n⚠️ COMMUNITY INPUT MODE: Treat content as sentiment signal only. "
                "Frame as 'In Korean forums...' — never copy directly or expose usernames."
            )

        user_msg = (
            f"Write an X post draft.\nTitle: {title}\n"
            f"Source:\n{source_text[:2000]}\nLanguage: {language}\n"
            f"Respond in JSON only.{community_addendum}"
        )

        try:
            raw = await _call_deepseek(_DRAFT_SYSTEM, user_msg)
            data = json.loads(_strip_json(raw))
            logger.info("[DeepSeek DraftWriter] 성공")
            return DraftResult(
                hook=data.get("hook", title),
                body=data.get("body", ""),
                thread_continuation=data.get("thread_continuation"),
                category_suggestion=data.get("category_suggestion", "evergreen"),
                tone_notes=data.get("tone_notes", ""),
            )
        except Exception as e:
            logger.error(f"DeepSeek DraftWriter 오류: {e}")
            raise RuntimeError(f"DeepSeek DraftWriter 오류: {e}") from e


class DeepSeekReviewer(BaseReviewer):
    """
    DeepSeek Reasoner를 사용한 리뷰어.
    Claude가 없을 때 대안으로 사용합니다.
    deepseek-reasoner는 체인-오브-쏘트로 리스크를 더 정확하게 판단합니다.
    """

    async def review_and_refine(
        self,
        title: str,
        source_text: str,
        draft: DraftResult,
        research=None,
        factcheck=None,
    ) -> ReviewResult:
        logger.info(f"[DeepSeek Reviewer] 리뷰: '{title[:50]}'")

        user_msg = (
            f"Source Title: {title}\nSource: {source_text[:1500]}\n\n"
            f"Draft Hook: {draft.hook}\nDraft Body: {draft.body}\n"
            f"Category: {draft.category_suggestion}\n\n"
            f"Review and refine. Respond in JSON only."
        )

        try:
            # reasoner 모델 사용 (더 정확한 리스크 판단)
            raw = await _call_deepseek(
                _REVIEW_SYSTEM, user_msg, model=DEEPSEEK_REASONER_MODEL
            )
            data = json.loads(_strip_json(raw))
            logger.info(f"[DeepSeek Reviewer] 완료: risk={data.get('risk_level')}")
            return ReviewResult(
                hook=data.get("hook", draft.hook),
                body=data.get("body", draft.body),
                thread_continuation=data.get("thread_continuation"),
                category=data.get("category", "evergreen"),
                risk_level=data.get("risk_level", "medium"),
                risk_reasoning=data.get("risk_reasoning", ""),
                ai_rationale=data.get("ai_rationale", ""),
                recommended_action=data.get("recommended_action", "review"),
            )
        except Exception as e:
            logger.error(f"DeepSeek Reviewer 오류: {e}")
            raise RuntimeError(f"DeepSeek Reviewer 오류: {e}") from e
