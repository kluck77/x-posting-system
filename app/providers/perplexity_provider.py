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
from app.providers.base import BaseFactChecker, FactCheckResult, CriteriaSignals

logger = logging.getLogger(__name__)


def _load_editorial_prompt(filename: str) -> str:
    """editorial/system_prompts/ 에서 critic system prompt 를 읽어 반환.
    Phase A: fact_critic 용 유틸 (anthropic_provider 와 동일 패턴)."""
    import os
    base = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    path = os.path.join(base, "editorial", "system_prompts", filename)
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


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
                resp_data = resp.json()
                usage = resp_data.get("usage", {})
                logger.info(
                    f"[API-COST] perplexity {PERPLEXITY_MODEL} "
                    f"in={usage.get('prompt_tokens', '?')} "
                    f"out={usage.get('completion_tokens', '?')} "
                    f"caller=FactChecker"
                )
                try:
                    from app.services.api_cost_tracker import record_usage
                    record_usage("perplexity", PERPLEXITY_MODEL, "FactChecker",
                                 usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0))
                except Exception:
                    pass
                raw_text = resp_data["choices"][0]["message"]["content"]

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

            # CriteriaSignals 구성 — interpretation + marketability 신호 매핑
            criteria_signals = CriteriaSignals(
                interpretation={
                    "score": None,
                    "note": interp,
                } if interp else {},
                marketability={
                    "score": None,
                    "note": f"signal={mkt}",
                } if mkt else {},
            )
            if criteria_signals.any_populated():
                logger.info(f"[Perplexity] criteria_signals: {criteria_signals.to_log_str()}")

            return FactCheckResult(
                verified=data.get("verified", False),
                confidence=data.get("confidence", "low"),
                corrections=data.get("corrections", []),
                sources=data.get("sources", []),
                raw_response=raw_text,
                interpretation_opportunity=interp,
                marketability_signal=mkt,
                criteria_signals=criteria_signals,
            )

        except Exception as e:
            logger.error(f"Perplexity FactChecker 오류: {e}")
            raise RuntimeError(f"Perplexity FactChecker 오류: {e}") from e

    # ── Phase A: fact critic (review 확정 + existing factcheck 기반) ────

    async def fact_critic(self, draft: str, existing_facts: dict) -> dict:
        """Fact Checker critic pass.
        editorial/system_prompts/fact_checker.md 를 system prompt 로 사용.
        existing_facts: check_facts() 결과를 dict 화한 값.
        반환: fact_checker JSON schema 준수 dict (publish_block 포함).
        실패 시 fallback dict 반환 (파이프라인 중단 없음)."""
        try:
            system_prompt = _load_editorial_prompt("fact_checker.md")
            user_content = (
                f"DRAFT:\n{draft}\n\n"
                f"EXISTING_FACTCHECK:\n"
                f"{json.dumps(existing_facts or {}, ensure_ascii=False)}"
            )
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
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_content},
                        ],
                        "temperature": 0.1,
                    },
                )
                resp.raise_for_status()
                text = resp.json()["choices"][0]["message"]["content"].strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1] if "\n" in text else text[3:]
                if text.endswith("```"):
                    text = text[:-3]
                text = text.strip()
            return json.loads(text)
        except Exception as e:
            return {
                "fact_check_passed": True,
                "publish_block": False,
                "claims": [],
                "translation_flags": [],
                "publish_block_reason": None,
                "summary": f"fact_critic fallback — {str(e)}",
            }
