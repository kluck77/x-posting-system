"""
xAI Grok 프로바이더
====================
역할: TrendHunter — 실시간 트렌드 탐지.
X/Twitter에서 한국 관련 트렌딩 토픽을 탐지하고 분석합니다.

Grok API는 OpenAI 호환 형식을 사용합니다.
"""

import json
import logging
import httpx
from app.config import settings
from app.providers.base import BaseTrendHunter, TrendResult

logger = logging.getLogger(__name__)

GROK_API_URL = "https://api.x.ai/v1/chat/completions"
GROK_MODEL = "grok-3-mini-fast"

SYSTEM_PROMPT = """You are the trend hunter for @cheesesvav — an English-language X account that shares Korean community perspectives with global readers.

Your job: Identify what Korean online communities and X/Twitter are talking about RIGHT NOW. Find trending topics that would interest English-speaking audiences who want to understand Korea.

Focus areas:
- Korean economic news generating buzz
- Korean online community hot topics (DCInside, FMKorea, crypto boards)
- Korean government policy reactions
- K-pop and cultural phenomena with broader implications
- Korean crypto/market sentiment shifts
- Social trends (employment, housing, demographics)

For each trend, assess:
- How much engagement it's getting
- Whether it's relevant for non-Korean audiences
- The sentiment (positive/negative/mixed)
- Time sensitivity (breaking now vs. ongoing)

STRICT RULES:
- Focus on topics with GLOBAL relevance or surprising aspects
- Skip purely domestic gossip with no broader implication
- Prioritize topics where Korean perspective differs from Western coverage
- Include specific numbers (engagement counts, percentages) when available

Respond in JSON ONLY:
{
  "trending_topics": [
    {
      "topic": "short topic title",
      "description": "1-2 sentence description",
      "sentiment": "positive|negative|mixed|neutral",
      "urgency": "breaking|trending|ongoing",
      "relevance_score": 1-10
    }
  ],
  "relevance_notes": "overall assessment of current Korean trend landscape"
}"""


class GrokTrendHunter(BaseTrendHunter):
    """xAI Grok을 사용한 트렌드 탐지기."""

    async def find_trends(self, topic_area: str = "korea") -> TrendResult:
        logger.info(f"[Grok TrendHunter] 트렌드 탐색: '{topic_area}'")

        user_msg = (
            f"Find current trending topics in Korean online communities and X/Twitter "
            f"related to: {topic_area}\n\n"
            f"Focus on topics that would surprise or interest English-speaking audiences.\n"
            f"Respond in JSON only."
        )

        try:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(
                    GROK_API_URL,
                    headers={
                        "Authorization": f"Bearer {settings.grok_api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": GROK_MODEL,
                        "messages": [
                            {"role": "system", "content": SYSTEM_PROMPT},
                            {"role": "user", "content": user_msg},
                        ],
                        "temperature": 0.5,
                    },
                )
                resp.raise_for_status()
                raw_text = resp.json()["choices"][0]["message"]["content"]

                # Grok may return markdown-wrapped JSON, strip it
                text = raw_text.strip()
                if text.startswith("```"):
                    text = text.split("\n", 1)[1] if "\n" in text else text[3:]
                    if text.endswith("```"):
                        text = text[:-3]
                    text = text.strip()

                data = json.loads(text)

            topics_raw = data.get("trending_topics", [])
            # Normalize: could be list of strings or list of dicts
            topics = []
            for t in topics_raw:
                if isinstance(t, str):
                    topics.append(t)
                elif isinstance(t, dict):
                    topics.append(t.get("topic", str(t)))

            logger.info(f"[Grok TrendHunter] {len(topics)}개 트렌드 발견")
            return TrendResult(
                trending_topics=topics,
                relevance_notes=data.get("relevance_notes", ""),
                raw_response=raw_text,
            )

        except Exception as e:
            logger.error(f"Grok TrendHunter 오류: {e}")
            raise RuntimeError(f"Grok TrendHunter 오류: {e}") from e
