"""
Groq 고속 프로바이더
=====================
역할: FastDraftWriter — 속보 대응 초고속 초안 생성.

Groq은 LPU(Language Processing Unit)로 OpenAI 호환 API를 제공합니다.
강점:
  - 응답 시간: ~100ms (GPT 대비 20배 빠름) — 속보 1분 내 초안 필수
  - 무료 티어: 30 req/min, 6000 tokens/min
  - 모델: Llama 4 Scout / Llama 3.3 70B

Groq ≠ Grok (xAI). 완전히 다른 서비스입니다.

모델:
  - meta-llama/llama-4-scout-17b-16e-instruct: 최신 Llama 4 (빠르고 강력)
  - llama-3.3-70b-versatile: 검증된 대형 모델
"""

import json
import logging
import re
import httpx
from app.config import settings
from app.providers.base import BaseDraftWriter, DraftResult

logger = logging.getLogger(__name__)

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL_PRIMARY   = "meta-llama/llama-4-scout-17b-16e-instruct"
GROQ_MODEL_FALLBACK  = "llama-3.3-70b-versatile"

_SYSTEM_PROMPT = """You are the FAST draft writer for @cheesesvav.
Identity: "Beyond headlines: how Korea really works, feels, and changes."
No name. Just signal. Breaking news mode — speed matters.

5-block structure: HOOK → FACT → TAKE → FOREIGN CONTEXT → CTA

Hook types: NUMBER SHOCK / CONTRADICTION / TIMING EDGE / PERSONAL STAKE / CONTRARIAN / BURIED STORY
Example CTAs:
- "Most Korea coverage is 12 hours late. Mine isn't. Follow."
- "No name. Just signal. Follow to stay ahead of Korean markets."
- "Korea's crypto traders are 2 weeks ahead. I track them. Follow."

RULES:
- NEVER start with "South Korea" / "Korea's"
- Body ≤ 270 chars — NON-NEGOTIABLE
- Hook needs a number OR contradiction OR timing signal
- Use "you". One opinion. No hedging.

JSON response ONLY:
{
  "hook": "scroll-stopping first line",
  "body": "under 270 chars: fact + take + context + CTA",
  "thread_continuation": null,
  "category_suggestion": "politics|policy|economy|society|crypto|kpop_culture|evergreen|community",
  "content_pillar": "economy|crypto|geopolitics|community",
  "optimal_post_time": "09:00 EST",
  "tone_notes": "hook type and angle"
}"""


def _strip_json(text: str) -> str:
    text = re.sub(r"^```(?:json)?\s*", "", text.strip())
    return re.sub(r"\s*```$", "", text).strip()


class GroqFastWriter(BaseDraftWriter):
    """
    Groq LPU 기반 초고속 초안 작성기.
    속보 알림 수신 직후 100ms 내 초안 생성 목표.
    Llama 4 Scout → fallback Llama 3.3 70B.
    """

    async def generate_draft(
        self,
        title: str,
        source_text: str,
        language: str = "en",
        source_type: str = "manual",
    ) -> DraftResult:
        logger.info(f"[Groq FastWriter] 초안 생성: '{title[:50]}'")

        community_note = ""
        if source_type == "community_input":
            community_note = (
                " [COMMUNITY MODE: Frame as 'In Korean forums...' "
                "— sentiment signal only, no usernames]"
            )

        user_msg = (
            f"Fast draft for breaking news.\n"
            f"Title: {title}\nSource:\n{source_text[:1500]}\n"
            f"Language: {language}{community_note}\nJSON only."
        )

        for model in [GROQ_MODEL_PRIMARY, GROQ_MODEL_FALLBACK]:
            try:
                async with httpx.AsyncClient(timeout=30) as client:
                    resp = await client.post(
                        GROQ_API_URL,
                        headers={
                            "Authorization": f"Bearer {settings.groq_api_key}",
                            "Content-Type": "application/json",
                        },
                        json={
                            "model": model,
                            "messages": [
                                {"role": "system", "content": _SYSTEM_PROMPT},
                                {"role": "user", "content": user_msg},
                            ],
                            "temperature": 0.7,
                            "response_format": {"type": "json_object"},
                            "max_tokens": 512,
                        },
                    )
                    resp.raise_for_status()
                    raw = resp.json()["choices"][0]["message"]["content"]
                    data = json.loads(_strip_json(raw))

                    logger.info(f"[Groq FastWriter] 성공 ({model})")
                    return DraftResult(
                        hook=data.get("hook", title),
                        body=data.get("body", ""),
                        thread_continuation=data.get("thread_continuation"),
                        category_suggestion=data.get("category_suggestion", "evergreen"),
                        tone_notes=data.get("tone_notes", ""),
                    )
            except Exception as e:
                logger.warning(f"[Groq FastWriter] {model} 실패: {e}")
                continue

        raise RuntimeError("Groq FastWriter: 모든 모델 실패")
