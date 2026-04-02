"""
Mistral AI 프로바이더
======================
역할: Reviewer (대안) — 리스크 판단 & 최종 다듬기.

강점:
  - 유럽 AI — GDPR 완전 준수 (민감 데이터 처리 안전)
  - Claude가 없을 때 최고의 대안 리뷰어
  - mistral-large-latest: Claude 수준의 추론 능력
  - OpenAI 호환 API

모델:
  - mistral-large-latest: 최고 품질 리뷰
  - mistral-small-latest: 빠르고 저렴한 리뷰
"""

import json
import logging
import re
import httpx
from app.config import settings
from app.providers.base import BaseReviewer, DraftResult, ReviewResult

logger = logging.getLogger(__name__)

MISTRAL_API_URL = "https://api.mistral.ai/v1/chat/completions"
MISTRAL_MODEL   = "mistral-large-latest"

_REVIEW_SYSTEM = """You are the editorial reviewer for @cheesesvav.
Account: "Beyond headlines: how Korea really works, feels, and changes."
Anonymous curator. No name. Just signal.

Review the draft:
1. Hook doesn't start with "South Korea"/"Korea's"
2. Specific number or contradiction in hook
3. Body ≤ 270 characters (enforce strictly)
4. CTA present (Follow/Bookmark)
5. Risk: politics/economy/crypto/society = medium+; evergreen = can be low
6. Is there at least one piece of context AP/Reuters would miss?

Respond in JSON ONLY:
{
  "hook": "final hook",
  "body": "final body (≤ 270 chars)",
  "thread_continuation": null,
  "category": "politics|policy|economy|society|crypto|kpop_culture|evergreen|community",
  "risk_level": "low|medium|high",
  "risk_reasoning": "one sentence",
  "ai_rationale": "why this draft earns a follow",
  "recommended_action": "approve|review|reject"
}"""


def _strip_json(text: str) -> str:
    text = re.sub(r"^```(?:json)?\s*", "", text.strip())
    return re.sub(r"\s*```$", "", text).strip()


class MistralReviewer(BaseReviewer):
    """
    Mistral Large를 사용한 리뷰어.
    Claude Reviewer의 대안 — GDPR 준수, 유럽 서버 옵션.
    """

    async def review_and_refine(
        self,
        title: str,
        source_text: str,
        draft: DraftResult,
        research=None,
        factcheck=None,
    ) -> ReviewResult:
        logger.info(f"[Mistral Reviewer] 리뷰: '{title[:50]}'")

        user_msg = (
            f"Source Title: {title}\nSource: {source_text[:1500]}\n\n"
            f"Draft Hook: {draft.hook}\nDraft Body: {draft.body}\n"
            f"Category: {draft.category_suggestion}\n\n"
            f"Review and refine. JSON only."
        )

        try:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(
                    MISTRAL_API_URL,
                    headers={
                        "Authorization": f"Bearer {settings.mistral_api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": MISTRAL_MODEL,
                        "messages": [
                            {"role": "system", "content": _REVIEW_SYSTEM},
                            {"role": "user", "content": user_msg},
                        ],
                        "temperature": 0.3,
                        "response_format": {"type": "json_object"},
                    },
                )
                resp.raise_for_status()
                raw = resp.json()["choices"][0]["message"]["content"]
                data = json.loads(_strip_json(raw))

            logger.info(f"[Mistral Reviewer] 완료: risk={data.get('risk_level')}")
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
            logger.error(f"Mistral Reviewer 오류: {e}")
            raise RuntimeError(f"Mistral Reviewer 오류: {e}") from e
