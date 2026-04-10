"""
Google Gemini 프로바이더
========================
역할: Researcher — 리서치 & 데이터 분석.
소스 텍스트에 대한 배경 정보, 관련 팩트, 맥락을 제공합니다.
"""

import json
import logging
import httpx
from app.config import settings
from app.providers.base import BaseResearcher, ResearchResult, CriteriaSignals

logger = logging.getLogger(__name__)

GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
GEMINI_MODEL = "gemini-2.0-flash"

SYSTEM_INSTRUCTION = """You are the research analyst for @cheesesvav — an English-language X account that shares Korean community perspectives with global readers.

Your job: Given a topic from Korean online communities or news, provide background research that helps write an accurate, engaging X post.

You must return:
1. A concise summary of the topic and its significance
2. Key verifiable facts (with numbers when possible)
3. Relevant context that non-Korean readers would need
4. Source suggestions for verification

Focus areas:
- Korean economic data, policy changes, market moves
- Korean online community sentiment and trends
- Cultural context that explains Korean reactions
- Global implications of Korean developments

STRICT RULES:
- Only include verifiable facts in key_facts
- Separate confirmed facts from community sentiment
- If information is from Korean communities (DCInside, FMKorea, etc.), label it as "community sentiment"
- Include specific numbers and dates when available

══════════════════════════════════════════
5-CRITERIA SUPPORT — interpretation infrastructure
══════════════════════════════════════════

This account's edge is interpretation, not translation. Your research must actively support that.

INTERPRETATION GAPS (Criteria 1 — Expertise):
Identify what mainstream English coverage (Reuters, AP, Bloomberg) is MISSING or getting wrong.
These gaps are the raw material for non-obvious interpretation.
Examples:
- "Reuters reports the policy change but misses that it contradicts Korea's 5-year plan"
- "Bloomberg covers the number but not why Korean investors see it differently"

FACT LABELS (Criteria 1 support):
Label each key fact based on how useful it is for interpretation:
- "challenges_assumption": Fact contradicts what most English readers would expect — HIGH VALUE
- "missing_context": Fact requires Korean context to understand properly — HIGH VALUE
- "confirms_common_narrative": Fact aligns with what Reuters already reported — LOW VALUE

Prioritize finding "challenges_assumption" and "missing_context" facts.

Respond in JSON ONLY:
{
  "summary": "2-3 sentence overview of the topic and why it matters",
  "key_facts": ["fact 1 with number", "fact 2 with date", "..."],
  "sources": ["source description 1", "source description 2"],
  "context_for_foreigners": "what non-Koreans need to know to understand this",
  "interpretation_gaps": [
    "what Reuters/Bloomberg misses about this story",
    "structural or cultural context that changes the interpretation"
  ],
  "fact_labels": {
    "fact text": "challenges_assumption|missing_context|confirms_common_narrative"
  }
}"""


class GeminiResearcher(BaseResearcher):
    """Google Gemini를 사용한 리서처."""

    async def research(self, query: str, context: str = "") -> ResearchResult:
        logger.info(f"[Gemini Researcher] 리서치: '{query[:60]}'")

        user_msg = (
            f"Research this Korean topic for an X post.\n\n"
            f"Topic: {query}\n\n"
        )
        if context:
            user_msg += f"Additional context:\n{context[:2000]}\n\n"
        user_msg += "Respond in JSON only."

        try:
            url = GEMINI_API_URL.format(model=GEMINI_MODEL)
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(
                    url,
                    params={"key": settings.gemini_api_key},
                    headers={"Content-Type": "application/json"},
                    json={
                        "system_instruction": {
                            "parts": [{"text": SYSTEM_INSTRUCTION}],
                        },
                        "contents": [
                            {
                                "parts": [{"text": user_msg}],
                            },
                        ],
                        "generationConfig": {
                            "temperature": 0.4,
                            "responseMimeType": "application/json",
                        },
                    },
                )
                resp.raise_for_status()
                raw_text = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
                data = json.loads(raw_text)

            gaps = data.get("interpretation_gaps", [])
            labels = data.get("fact_labels", {})
            high_value = [f for f, lbl in labels.items() if lbl != "confirms_common_narrative"]

            if gaps:
                logger.info(f"[Gemini Researcher] 해석 갭 {len(gaps)}개 발견: {gaps[0][:80]}")
            if high_value:
                logger.info(f"[Gemini Researcher] 고가치 팩트 {len(high_value)}개 (challenges/missing)")
            logger.info("[Gemini Researcher] 리서치 성공")

            # CriteriaSignals 구성 — expertise(해석 갭) + context_gap(고가치 팩트)
            criteria_signals = CriteriaSignals(
                expertise={
                    "score": None,
                    "note": f"해석 갭 {len(gaps)}개 발견",
                } if gaps else {},
                context_gap={
                    "score": None,
                    "note": (
                        f"고가치 팩트 {len(high_value)}개 "
                        f"(challenges_assumption/missing_context)"
                    ),
                } if high_value else {},
            )
            if criteria_signals.any_populated():
                logger.info(f"[Gemini] criteria_signals: {criteria_signals.to_log_str()}")

            return ResearchResult(
                summary=data.get("summary", ""),
                key_facts=data.get("key_facts", []),
                sources=data.get("sources", []),
                raw_response=raw_text,
                interpretation_gaps=gaps,
                fact_labels=labels,
                criteria_signals=criteria_signals,
            )

        except Exception as e:
            logger.error(f"Gemini Researcher 오류: {e}")
            raise RuntimeError(f"Gemini Researcher 오류: {e}") from e
