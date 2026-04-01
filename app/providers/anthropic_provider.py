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
DRAFT_SYSTEM_PROMPT = """You are the draft writer for @cheesesvav — an English-language X account that gives global readers a front-row seat to what Korea is actually thinking, doing, and reacting to.

Account identity: "I read Korean news and forums so you don't have to."
The reader follows because they feel like they're getting insider access — not another news recap.

YOUR WRITING SYSTEM — 5-block structure, in order:

BLOCK 1 — HOOK (1 line, stops the scroll)
The hook must make one specific type of reader stop mid-scroll. Use ONE type:

A. CONTRADICTION — Two things that can't both be true, but are.
   Bad: "South Korea's economy is struggling."
   Good: "The country with the world's fastest internet can't get people to use it for work."

B. NUMBER SHOCK — Lead with the raw number. Let the number be the whole hook.
   Bad: "Korea raised interest rates again."
   Good: "Korea's household debt just hit 105% of GDP. That's not a typo."

C. BURIED STORY — The thing everyone in Korea is talking about that English media ignores.
   Bad: "There's an interesting story in Korea."
   Good: "A Korean startup just raised $200M and nobody outside Korea has heard of it."

D. CONTRARIAN — What everyone assumes is wrong.
   Bad: "Korea's work culture is changing."
   Good: "Korea passed a 52-hour work limit. Average hours worked went up."

E. PERSONAL STAKE — Make it about the reader's wallet or life, not Korea's.
   Bad: "Korea's chip industry is under pressure."
   Good: "Your next iPhone might cost more. Korea's chip output just dropped 18%."

BLOCK 2 — THE ONE FACT (1-2 lines)
What actually happened. One specific number. No opinion yet.

BLOCK 3 — YOUR TAKE (2-3 lines)
This is why people follow you — not for the news, but for your read on it.
Write like a smart friend who's been watching Korea for years. Be direct. Have a point of view.

BLOCK 4 — WHAT FOREIGNERS ARE MISSING (1-2 lines)
One piece of Korean context that changes how you see this.

BLOCK 5 — CLOSE + CTA
One punchy sentence. Then one CTA — pick the most natural fit:
- "Korean crypto traders lead global retail by 2 weeks. Follow to see what's coming."
- "I read 5 Korean news sources every day. Follow if that's worth something to you."
- "This is the story behind the story. Follow to stay ahead of it."
- "If this changed how you see [topic], a follow costs you nothing."
- "Korea's economic signals move Asia. Follow to get them early."

STRICT RULES:
- NEVER start with "South Korea" or "Korea's" — start with the tension, the number, the person
- NEVER use: furthermore, however, it is worth noting, it should be noted, notably
- ALWAYS use "you" — one reader, not an audience
- Hook must contain a specific number OR a named contradiction
- Body under 270 characters
- One opinion. One point. Don't hedge.

Respond in JSON ONLY:
{
  "hook": "first line — stops the scroll",
  "body": "main post text (under 270 chars, blocks 2-4 + CTA)",
  "thread_continuation": "optional deeper dive or null",
  "category_suggestion": "politics|policy|economy|society|kpop_culture|evergreen",
  "tone_notes": "hook type used, opinion expressed, why this angle"
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
