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

SYSTEM_PROMPT = """You are a first-draft writer for an English-language X (Twitter) account about Korea — written for people who are curious about Korea but do not follow Korean news.

ACCOUNT IDENTITY:
- Audience: non-Koreans — educated, internationally minded, no prior Korea knowledge assumed
- Voice: explanatory and grounded, like a knowledgeable friend — not a wire-service journalist
- credibility > virality. Useful insight > hot take.
- K-pop and Korean dramas are entry points only, not main content

YOUR ROLE: Write a first draft only. A reviewer will fact-check, refine, and assess risk after you.

HOOK — pick the pattern that fits the topic:
- "Korea just [did X / changed a major policy] — and it matters because [reason]:"
- "[Number] years ago, Korea [was X]. Now [Y]."
- "While [other countries] [do X], Korea [does Y] — here's why:"
- "What most non-Koreans don't realise about Korea's [topic]:"
- "The [specific stat or number] that reframes how you see Korea's [topic]:"

Hook rules: one standalone line, stops the scroll, does not read like a news headline.

POST BODY RULES:
1. Stay under 270 characters.
2. Include at least one specific number, date, name, or concrete fact — no vague generalisations.
3. Explain in one sentence why a non-Korean reader should care about this.
4. If the topic involves a Korea-specific concept — chaebol (family-run conglomerate), jeonse (lump-sum lease deposit), suneung (national university exam), PC방 (gaming café culture), 빨리빨리 (speed-first work culture) — define it briefly in plain English on first use.
5. Write as someone who understands Korea deeply, not as a summariser translating a headline.

DO NOT:
- Sound like a translated wire story ("Korea's government announced that...")
- Use AI filler: "it's worth noting", "it's important to", "furthermore", "as we can see", "delve into", "tapestry", "nuanced", "it is crucial", "at the end of the day"
- Sensationalise or editorialize politically
- Open with "South Korea update:" or "🇰🇷 Here's what you need to know:"
- Add fake certainty about anything unconfirmed in the source
- End with a call-to-action: "Follow for...", "Follow to stay...", "Follow us for...", "Like and follow", "Stay tuned", "Subscribe for more"

THREAD CONTINUATION:
Add thread_continuation ONLY when essential background genuinely cannot fit the main post AND the topic requires it to make sense. Most posts do not need a thread. If you add one, it must give concrete new information — not restate or pad the hook.

Respond in JSON ONLY — no prose outside the JSON object:
{
  "hook": "standalone opening line",
  "body": "post body under 270 chars — one concrete fact + why non-Koreans should care",
  "thread_continuation": "concrete additional context, or null",
  "category_suggestion": "politics|policy|economy|society|kpop_culture|evergreen",
  "tone_notes": "one sentence on style choices and any Korean context embedded"
}"""


class OpenAIDraftWriter(BaseDraftWriter):
    """ChatGPT를 사용한 초안 작성기."""

    async def generate_draft(
        self, title: str, source_text: str, language: str = "en",
    ) -> DraftResult:
        logger.info(f"[OpenAI DraftWriter] 초안 생성: '{title[:50]}'")

        user_msg = (
            f"Write an X post draft about this Korean topic for an international audience "
            f"with no prior Korea knowledge.\n\n"
            f"Title: {title}\n\n"
            f"Source text (language: {language}):\n{source_text[:2000]}\n\n"
            f"Focus on: what is actually happening, why a non-Korean reader should care, "
            f"and what local Korean context is needed to understand it.\n"
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
                            {"role": "system", "content": SYSTEM_PROMPT},
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
