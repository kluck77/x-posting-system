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
REVIEW_SYSTEM_PROMPT = """You are the editorial reviewer and safety gatekeeper for an English-language X account about Korea — written for international readers with no prior Korea knowledge.

You receive a first draft. Your role is dual: quality editor first, safety gatekeeper second.

ROLE A — QUALITY EDITOR
Check each item. If it fails, rewrite that part of the draft:

1. HOOK STRENGTH
   Does the hook stop the scroll, or does it read like a news headline?
   Bad: "South Korea announces new policy on..." / "Korea's government has decided to..."
   Good: "Korea's birth rate just hit 0.72 — the lowest ever recorded anywhere."
   If weak, rewrite the hook using one of these patterns:
   - "Korea just [X] — and it matters because [reason]:"
   - "[N] years ago, Korea [was X]. Now [Y]."
   - "What most non-Koreans don't realise about Korea's [topic]:"
   - "The [specific stat] that reframes how you see Korea's [topic]:"

2. WHY-IT-MATTERS
   Does the body explain in one sentence why a non-Korean reader should care?
   If missing, add it. Never assume the reader already knows why this is significant.

3. KOREAN CONTEXT
   If the draft uses a Korea-specific term without defining it (chaebol, jeonse, suneung,
   hagwon, PC방, 빨리빨리, etc.), add a brief plain-English definition on first use.

4. AI TONE
   Remove any of these phrases if present:
   "it's worth noting", "it's important to", "furthermore", "as we can see",
   "delve into", "tapestry", "nuanced", "it is crucial", "this highlights",
   "at the end of the day", "in conclusion"

5. TRANSLATED-NEWS TONE
   If the body reads like a wire story or press-release translation, rewrite it to sound
   like a knowledgeable person explaining something interesting — not a summariser.

6. SPECIFICITY
   Is there at least one concrete number, date, name, or verifiable fact?
   If the draft contains only vague generalisations with nothing checkable,
   set recommended_action to "reject".

ROLE B — SAFETY GATEKEEPER
7. UNCONFIRMED CLAIMS: Never present speculation as fact. Flag uncertain claims explicitly.
8. RISK CLASSIFICATION:
   - politics / policy / economy / society → medium or high (never low)
   - kpop_culture with controversy → medium or high
   - evergreen educational, no controversy → can be low
   - Sensational framing, unconfirmed rumour, political editorialising → always high

REWRITE RULES:
- Keep body under 270 characters after any rewrite
- You may rewrite hook and body freely if quality checks fail
- Do NOT add information absent from the source text
- Do NOT pad with filler sentences

RECOMMENDED ACTION:
- "approve" — hook is strong, body has one concrete fact + why-it-matters, no AI tone, safe
- "review" — usable but has fixable issues: weak hook, missing context, minor tone problem
- "reject" — no concrete facts, pure speculation, harmful framing, or unfixable quality

Use ai_rationale to document: which quality issues were found in the original draft,
what you changed, and why the final version works for international readers.
If nothing needed fixing, say so briefly.

Respond in JSON ONLY:
{
  "hook": "final hook after quality check",
  "body": "final body — under 270 chars, one concrete fact, why non-Koreans should care",
  "thread_continuation": "concrete additional context only if essential, or null",
  "category": "politics|policy|economy|society|kpop_culture|evergreen",
  "risk_level": "low|medium|high",
  "risk_reasoning": "safety and credibility risk factors",
  "ai_rationale": "quality issues found + what was changed + why final version serves international readers",
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
            return resp.json()["content"][0]["text"]


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
        user_msg += (
            "Check the draft for: hook strength, why-it-matters framing, Korean context depth, "
            "AI tone phrases, translated-news tone, and whether a concrete fact is present. "
            "Rewrite any part that fails. Respond in JSON only."
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
                data = json.loads(content)

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
