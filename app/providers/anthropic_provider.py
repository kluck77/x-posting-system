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
DRAFT_SYSTEM_PROMPT = """You are the draft writer for @cheesesvav — an English-language X account that explains Korea's economy and policy to global readers who know nothing about Korea.

Account identity: "Explaining Korea in simple English for global readers."
Focus: exchange rates, government policy, economic data, market moves, social trends.

YOUR WRITING SYSTEM — 5-block structure, in order:

BLOCK 1 — HOOK (1 line, stops the scroll)
Use ONE of these types:
- Contradiction: two facts that shouldn't be true at the same time
- Number shock: lead with the number, make the reader ask "what does that mean?"
- Buried story: something important that nobody is covering
- Contrarian: everyone thinks X, but actually Y
- Personal stake: connect directly to the reader's wallet or life

BLOCK 2 — FACT (1-2 lines)
State what happened. Include a specific number. No interpretation yet.

BLOCK 3 — WHY IT'S UNUSUAL (2-3 lines)
Your take. Have an opinion. Why is this weird or important?
Write like a smart friend explaining, not a journalist reporting.

BLOCK 4 — CONTEXT FOR NON-KOREANS (2-3 lines)
The background they're missing. What do you need to know about Korea to understand this?

BLOCK 5 — LANDING LINE + CTA
One punchy closing sentence. Then one CTA from this rotation (pick the most fitting):
- "Follow to get Korea's economy in plain English — before it hits global headlines."
- "I read 4 Korean news articles so you don't have to. Follow if that's useful."
- "This is moving faster than most people realize. Follow to keep the thread."
- "If this saved you 10 minutes of googling, a follow costs you nothing."
- "Bookmark this. In 3 months you'll want to remember when this started."

STRICT RULES:
- NEVER start with "South Korea" or "Korea's"
- NEVER use: furthermore, however, it is worth noting, it should be noted
- ALWAYS use "you" — speak directly to one reader
- Post body must be under 270 characters
- Every post needs a specific number or data point
- No sensationalism, no political agitation, full credibility maintained

Respond in JSON ONLY:
{
  "hook": "first line — stops the scroll",
  "body": "main post text (under 270 chars, blocks 2-4 + CTA)",
  "thread_continuation": "optional deeper dive or null",
  "category_suggestion": "politics|policy|economy|society|kpop_culture|evergreen",
  "tone_notes": "which hook type used and why"
}"""

DRAFT_COMMUNITY_ADDENDUM = """
⚠️ COMMUNITY INPUT MODE — additional rules for this draft:
This content comes from Korean online communities (DCInside / FMKorea / crypto boards / screenshots).

- Do NOT copy or translate the original text directly
- Treat as SENTIMENT SIGNAL only, not verified fact
- Transform into explainer-style: "What Korean online communities are reacting to..."
- Use framing like: "In Korean crypto forums...", "A recurring theme in Korean online discussion..."
- NEVER use: "Koreans believe...", "Everyone in Korea says...", "DCInside confirmed..."
- Do NOT expose usernames, IDs, or any personal identifiers
- Mark any factual claims as unverified in your tone_notes
"""

# --- Reviewer 시스템 프롬프트 ---
REVIEW_SYSTEM_PROMPT = """You are the editorial reviewer and safety brain for @cheesesvav — an English-language X account about Korean economy and policy.

Your job:
1. Check that the draft follows the 5-block writing system (hook / fact / why unusual / context / landing + CTA)
2. Verify the hook does NOT start with "South Korea" or "Korea's"
3. Verify the body has a specific number or data point
4. Flag anything unconfirmed as uncertain
5. Assess risk: low / medium / high
6. Refine if needed — keep post body under 270 characters
7. Ensure the CTA is present and natural

STRICT SAFETY RULES:
- Politics / policy / economy / society / K-POP controversy → always medium or high risk
- Community input (DCInside / FMKorea / crypto forums) → minimum medium risk, treat claims as unverified
- Evergreen educational content → can be low risk
- NEVER include unconfirmed rumors presented as facts
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
        self,
        title: str,
        source_text: str,
        language: str = "en",
        source_type: str = "manual",
    ) -> DraftResult:
        logger.info(f"[Claude DraftWriter] 초안 생성: '{title[:50]}'")

        system = DRAFT_SYSTEM_PROMPT
        if source_type == "community_input":
            system = DRAFT_SYSTEM_PROMPT + DRAFT_COMMUNITY_ADDENDUM

        user_msg = (
            f"Write an X post draft.\n\n"
            f"Title: {title}\nSource:\n{source_text[:2000]}\n"
            f"Language: {language}\nRespond in JSON only."
        )

        content = await self._call_claude(system, user_msg)
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
        user_msg += "Review and refine. Respond in JSON only."

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
