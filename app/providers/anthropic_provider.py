"""
Anthropic (Claude) 프로바이더
==============================
역할 2가지:
  - Draft Writer (대안): Claude도 초안을 쓸 수 있음
  - Reviewer (주역할): 리스크 판단, 팩트 체크, 최종 다듬기, 안전 검토

Claude는 시스템의 "두뇌" 역할입니다.
구조, 신뢰성, 안전 로직을 책임집니다.
"""

import json
import logging
import httpx
from app.config import settings
from app.providers.base import (
    BaseDraftWriter, BaseReviewer,
    DraftResult, ReviewResult, ResearchResult, FactCheckResult,
)

logger = logging.getLogger(__name__)

CLAUDE_API_URL = "https://api.anthropic.com/v1/messages"
CLAUDE_MODEL = "claude-sonnet-4-20250514"

# --- Draft Writer 시스템 프롬프트 ---
DRAFT_SYSTEM_PROMPT = """You are a draft writer for an English-language X account that explains Korean affairs to international audiences.
Write a first draft. Keep the post body under 270 characters. Be factual and balanced.

Respond in JSON ONLY:
{
  "hook": "attention-grabbing opening line",
  "body": "main post text for X (under 270 chars)",
  "thread_continuation": "optional thread text or null",
  "category_suggestion": "politics|policy|economy|society|kpop_culture|evergreen",
  "tone_notes": "style notes"
}"""

# --- Reviewer 시스템 프롬프트 ---
REVIEW_SYSTEM_PROMPT = """You are the editorial reviewer and safety brain for an English-language X account about Korean affairs.

You receive a draft and optional research/factcheck data. Your job:
1. Verify facts where possible
2. Flag anything unconfirmed as uncertain
3. Assess risk: low / medium / high
4. Refine the draft into a polished, balanced post
5. Keep post body under 270 characters

STRICT SAFETY RULES:
- Politics / policy / economy / society / K-POP controversy → always medium or high risk
- Evergreen educational content → can be low risk
- NEVER include unconfirmed rumors
- NEVER sensationalize

Respond in JSON ONLY:
{
  "hook": "final hook",
  "body": "final post body (under 270 chars)",
  "thread_continuation": "optional or null",
  "category": "politics|policy|economy|society|kpop_culture|evergreen",
  "risk_level": "low|medium|high",
  "risk_reasoning": "why this risk level",
  "ai_rationale": "why this draft serves the audience well",
  "recommended_action": "approve|review|reject"
}"""


class AnthropicDraftWriter(BaseDraftWriter):
    """Claude를 사용한 초안 작성기 (대안 드래프트 역할)."""

    async def generate_draft(
        self, title: str, source_text: str, language: str = "en",
    ) -> DraftResult:
        logger.info(f"[Claude DraftWriter] 초안 생성: '{title[:50]}'")

        user_msg = (
            f"Write an X post draft.\n\n"
            f"Title: {title}\nSource:\n{source_text[:2000]}\n"
            f"Language: {language}\nRespond in JSON only."
        )

        content = await self._call_claude(DRAFT_SYSTEM_PROMPT, user_msg)
        data = json.loads(content)
        return DraftResult(
            hook=data.get("hook", title),
            body=data.get("body", ""),
            thread_continuation=data.get("thread_continuation"),
            category_suggestion=data.get("category_suggestion", "evergreen"),
            tone_notes=data.get("tone_notes", ""),
        )

    async def _call_claude(self, system: str, user_msg: str) -> str:
        # [Phase8α] diagnostic: log request parameters before HTTP call
        logger.info(
            f"[Phase8α][Claude DraftWriter] request model={CLAUDE_MODEL} "
            f"max_tokens=1024 user_msg_len={len(user_msg)}"
        )
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                CLAUDE_API_URL,
                headers={
                    "x-api-key": settings.anthropic_api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": CLAUDE_MODEL,
                    "max_tokens": 1024,
                    "system": system,
                    "messages": [{"role": "user", "content": user_msg}],
                },
            )
            resp.raise_for_status()
            content = resp.json()["content"][0]["text"]
            # [Phase8α] diagnostic: log raw response metadata + preview
            logger.info(
                f"[Phase8α][Claude DraftWriter] response http={resp.status_code} "
                f"content_len={len(content)}"
            )
            logger.debug(
                f"[Phase8α][Claude DraftWriter] raw_content_preview={content[:200]!r}"
            )
            return content


class AnthropicReviewer(BaseReviewer):
    """Claude를 사용한 리뷰어 (메인 역할)."""

    async def review_and_refine(
        self,
        title: str,
        source_text: str,
        draft: DraftResult,
        research: ResearchResult | None = None,
        factcheck: FactCheckResult | None = None,
    ) -> ReviewResult:
        logger.info(f"[Claude Reviewer] 리뷰: '{title[:50]}'")

        user_msg = (
            f"## Source\nTitle: {title}\nText: {source_text[:1500]}\n\n"
            f"## Draft to Review\nHook: {draft.hook}\nBody: {draft.body}\n"
            f"Thread: {draft.thread_continuation or 'none'}\n"
            f"Suggested category: {draft.category_suggestion}\n\n"
        )
        if research:
            user_msg += (
                f"## Research\nSummary: {research.summary[:500]}\n"
                f"Facts: {'; '.join(research.key_facts[:5])}\n\n"
            )
        if factcheck:
            user_msg += (
                f"## Fact Check\nVerified: {factcheck.verified}\n"
                f"Corrections: {'; '.join(factcheck.corrections[:3])}\n\n"
            )
        user_msg += "Review and refine. Respond in JSON only."

        # [Phase8α] diagnostic: log request parameters before HTTP call
        logger.info(
            f"[Phase8α][Claude Reviewer] request model={CLAUDE_MODEL} "
            f"max_tokens=1024 title='{title[:50]}' user_msg_len={len(user_msg)} "
            f"has_research={research is not None} has_factcheck={factcheck is not None}"
        )

        try:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(
                    CLAUDE_API_URL,
                    headers={
                        "x-api-key": settings.anthropic_api_key,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                    json={
                        "model": CLAUDE_MODEL,
                        "max_tokens": 1024,
                        "system": REVIEW_SYSTEM_PROMPT,
                        "messages": [{"role": "user", "content": user_msg}],
                    },
                )
                resp.raise_for_status()
                content = resp.json()["content"][0]["text"]
                # [Phase8α] diagnostic: log raw response metadata + preview
                logger.info(
                    f"[Phase8α][Claude Reviewer] response http={resp.status_code} "
                    f"content_len={len(content)}"
                )
                logger.debug(
                    f"[Phase8α][Claude Reviewer] raw_content_preview={content[:200]!r}"
                )
                data = json.loads(content)
                # [Phase8α] diagnostic: log parsed fields for observation
                logger.info(
                    f"[Phase8α][Claude Reviewer] parsed risk={data.get('risk_level')} "
                    f"category={data.get('category')} action={data.get('recommended_action')} "
                    f"body_len={len(data.get('body', '') or '')}"
                )

            logger.info(f"[Claude Reviewer] 완료: risk={data.get('risk_level')}")
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
            logger.error(f"Claude Reviewer 오류: {e}")
            raise RuntimeError(f"Claude Reviewer 오류: {e}") from e
