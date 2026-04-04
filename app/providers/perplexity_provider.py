"""
Perplexity 프로바이더
=====================
역할: FactChecker — 팩트체크 & 출처 찾기.
AI 생성 초안의 사실 관계를 검증하고 출처를 제공합니다.

Perplexity API는 OpenAI 호환 형식을 사용합니다.
"""

import json
import logging
import httpx
from app.config import settings
from app.providers.base import BaseFactChecker, FactCheckResult

logger = logging.getLogger(__name__)

PERPLEXITY_API_URL = "https://api.perplexity.ai/chat/completions"
PERPLEXITY_MODEL = "sonar"

SYSTEM_PROMPT = """You are the fact-checker for @cheesesvav — an English-language X account that shares Korean community perspectives with global readers.

Your job: Verify claims in draft X posts about Korea. Check numbers, dates, policy details, and contextual accuracy.

For each claim:
1. Is it verifiable? Can you find a source?
2. Is the number/date accurate?
3. Is the context correct? (not misleading even if technically true)
4. Are there important corrections needed?

STRICT RULES:
- Mark claims from Korean communities as "community sentiment — unverifiable"
- Do NOT verify opinions, only factual claims
- If a number is close but not exact, note the correct number
- If context is misleading, explain why
- Always provide source URLs when possible

Confidence levels:
- "high": Multiple reliable sources confirm
- "medium": One reliable source or partially confirmed
- "low": Cannot verify or conflicting information

══════════════════════════════════════════
5-CRITERIA SUPPORT — beyond fact-checking
══════════════════════════════════════════

After verifying the facts, also evaluate:

INTERPRETATION OPPORTUNITY (Criteria 1 — Expertise):
Does this verified fact create an opportunity for unique interpretation?
- "high": The fact contradicts common assumptions, reveals a structural issue, or tells a counter-intuitive story
  Example: "Korea's birth rate hits 0.72 — lowest ever, despite $200B in government spending" → high
- "medium": Fact is interesting but the interpretation is straightforward
- "low": Fact confirms what everyone already knows — adds no interpretive value

MARKETABILITY SIGNAL (Criteria 2 — Marketability):
Is this fact globally relevant, or only locally interesting?
- "global": Connects to international markets, supply chains, crypto, geopolitics, or tech
- "regional": Relevant to Asia/Pacific but not globally traded
- "local": Primarily meaningful to Koreans only

These fields are NOT corrections — they help the draft writer decide the angle and depth.

Respond in JSON ONLY:
{
  "verified": true/false,
  "confidence": "low|medium|high",
  "corrections": ["correction 1 if any", "correction 2 if any"],
  "sources": ["https://source-url-1", "https://source-url-2"],
  "details": "brief explanation of verification result",
  "interpretation_opportunity": "high|medium|low — one sentence reason",
  "marketability_signal": "global|regional|local"
}"""


class PerplexityFactChecker(BaseFactChecker):
    """Perplexity를 사용한 팩트체커."""

    async def check_facts(self, claim: str, context: str = "") -> FactCheckResult:
        logger.info(f"[Perplexity FactChecker] 검증: '{claim[:60]}'")

        user_msg = (
            f"Fact-check this claim from a draft X post about Korea.\n\n"
            f"Claim: {claim[:1500]}\n\n"
        )
        if context:
            user_msg += f"Source context:\n{context[:1000]}\n\n"
        user_msg += (
            "Verify the factual claims. Check numbers, dates, and context accuracy.\n"
            "Respond in JSON only."
        )

        try:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(
                    PERPLEXITY_API_URL,
                    headers={
                        "Authorization": f"Bearer {settings.perplexity_api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": PERPLEXITY_MODEL,
                        "messages": [
                            {"role": "system", "content": SYSTEM_PROMPT},
                            {"role": "user", "content": user_msg},
                        ],
                        "temperature": 0.1,
                    },
                )
                resp.raise_for_status()
                raw_text = resp.json()["choices"][0]["message"]["content"]

                # Handle potential markdown-wrapped JSON
                text = raw_text.strip()
                if text.startswith("```"):
                    text = text.split("\n", 1)[1] if "\n" in text else text[3:]
                    if text.endswith("```"):
                        text = text[:-3]
                    text = text.strip()

                data = json.loads(text)

            interp = data.get("interpretation_opportunity", "")
            mkt = data.get("marketability_signal", "")
            logger.info(
                f"[Perplexity FactChecker] 완료: "
                f"verified={data.get('verified')}, confidence={data.get('confidence')} | "
                f"interpretation={interp} marketability={mkt}"
            )
            return FactCheckResult(
                verified=data.get("verified", False),
                confidence=data.get("confidence", "low"),
                corrections=data.get("corrections", []),
                sources=data.get("sources", []),
                raw_response=raw_text,
                interpretation_opportunity=interp,
                marketability_signal=mkt,
            )

        except Exception as e:
            logger.error(f"Perplexity FactChecker 오류: {e}")
            raise RuntimeError(f"Perplexity FactChecker 오류: {e}") from e
