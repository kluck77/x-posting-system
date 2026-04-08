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

SYSTEM_PROMPT = """You are a draft writer for an English-language X (Twitter) account.
The account explains Korean society, policy, politics, and economy to non-Korean audiences.
K-POP and Korean dramas are used only as entry points or examples, not as main content.

Your job: write a FIRST DRAFT. Someone else will review, risk-check, and polish it.

Rules:
- Write in clear, accessible English
- Avoid jargon; explain Korean terms
- Be factual and balanced — do not sensationalize
- Keep the main post body under 270 characters
- Hook should grab attention
- Provide context non-Koreans need

Respond in JSON ONLY:
{
  "hook": "attention-grabbing opening line",
  "body": "main post text for X (under 270 chars)",
  "thread_continuation": "optional thread text or null",
  "category_suggestion": "politics|policy|economy|society|kpop_culture|evergreen",
  "tone_notes": "notes on your style choices"
}"""


class OpenAIDraftWriter(BaseDraftWriter):
    """ChatGPT를 사용한 초안 작성기."""

    async def generate_draft(
        self,
        title: str,
        source_text: str,
        language: str = "en",
        source_type: str = "manual",
        criteria_context: str = "",
    ) -> DraftResult:
        logger.info(f"[OpenAI DraftWriter] 초안 생성: '{title[:50]}'")

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
                hook=data.get("hook") or title,
                body=data.get("body") or "",
                thread_continuation=data.get("thread_continuation"),
                category_suggestion=data.get("category_suggestion", "evergreen"),
                tone_notes=data.get("tone_notes", ""),
            )

        except Exception as e:
            logger.error(f"OpenAI DraftWriter 오류: {e}")
            raise RuntimeError(f"OpenAI DraftWriter 오류: {e}") from e
