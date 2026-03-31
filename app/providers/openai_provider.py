"""
OpenAI (ChatGPT) 프로바이더
============================
역할: Draft Writer — 빠른 초안 생성, 톤 조정, 리라이팅.
ChatGPT는 절대 단독으로 게시 결정을 내리지 않습니다.
"""

import json
import logging
import httpx
from app.config import settings
from app.providers.base import BaseDraftWriter, DraftResult

logger = logging.getLogger(__name__)

OPENAI_API_URL = "https://api.openai.com/v1/chat/completions"
OPENAI_MODEL = "gpt-4o-mini"

SYSTEM_PROMPT = """You are the draft writer for @cheesesvav — an English-language X account that explains Korea's economy and policy to global readers who know nothing about Korea.

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

COMMUNITY_INPUT_ADDENDUM = """
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


class OpenAIDraftWriter(BaseDraftWriter):
    """ChatGPT를 사용한 초안 작성기."""

    async def generate_draft(
        self,
        title: str,
        source_text: str,
        language: str = "en",
        source_type: str = "manual",
    ) -> DraftResult:
        logger.info(f"[OpenAI DraftWriter] 초안 생성: '{title[:50]}'")

        system = SYSTEM_PROMPT
        if source_type == "community_input":
            system = SYSTEM_PROMPT + COMMUNITY_INPUT_ADDENDUM

        user_msg = (
            f"Write an X post draft about this Korean topic.\n\n"
            f"Title: {title}\n\n"
            f"Source text:\n{source_text[:2000]}\n\n"
            f"Target language: {language}\n"
            f"Respond in JSON only."
        )

        try:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(
                    OPENAI_API_URL,
                    headers={
                        "Authorization": f"Bearer {settings.openai_api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": OPENAI_MODEL,
                        "messages": [
                            {"role": "system", "content": system},
                            {"role": "user", "content": user_msg},
                        ],
                        "temperature": 0.7,
                        "response_format": {"type": "json_object"},
                    },
                )
                resp.raise_for_status()
                data = json.loads(resp.json()["choices"][0]["message"]["content"])

            logger.info("[OpenAI DraftWriter] 초안 생성 성공")
            return DraftResult(
                hook=data.get("hook", title),
                body=data.get("body", ""),
                thread_continuation=data.get("thread_continuation"),
                category_suggestion=data.get("category_suggestion", "evergreen"),
                tone_notes=data.get("tone_notes", ""),
            )

        except Exception as e:
            logger.error(f"OpenAI DraftWriter 오류: {e}")
            raise RuntimeError(f"OpenAI DraftWriter 오류: {e}") from e
