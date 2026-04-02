"""
Together AI 프로바이더
=======================
역할: DraftWriter (대안) — 오픈소스 최대 모델 접근.

강점:
  - Meta Llama 3.1 405B: 오픈소스 모델 중 최고 품질 (GPT-4급)
  - 오픈소스: 민감한 한국 정치/사회 콘텐츠에 더 유연
  - 가격: $3.5/M tokens (Llama 3.1 405B Instruct Turbo)
  - 빠른 추론 + 한국어 이해 준수
  - OpenAI 호환 API

모델:
  - meta-llama/Meta-Llama-3.1-405B-Instruct-Turbo: 최고 품질
  - meta-llama/Llama-3.3-70B-Instruct-Turbo: 균형 (빠름 + 저렴)
  - Qwen/Qwen2.5-72B-Instruct-Turbo: 한/중/일 언어 특화
"""

import json
import logging
import re
import httpx
from app.config import settings
from app.providers.base import BaseDraftWriter, DraftResult

logger = logging.getLogger(__name__)

TOGETHER_API_URL = "https://api.together.xyz/v1/chat/completions"

# 모델 선택 (우선순위 순)
TOGETHER_MODELS = [
    "meta-llama/Meta-Llama-3.1-405B-Instruct-Turbo",   # 최고 품질
    "Qwen/Qwen2.5-72B-Instruct-Turbo",                  # 아시아 언어 특화
    "meta-llama/Llama-3.3-70B-Instruct-Turbo",          # 빠르고 저렴
]

_SYSTEM_PROMPT = """You are the draft writer for @cheesesvav — an anonymous English-language X account.
Identity: "Beyond headlines: how Korea really works, feels, and changes."
No name. Just signal.

5-block structure: HOOK → FACT → TAKE → FOREIGN CONTEXT → CTA

Hook types: CONTRADICTION / NUMBER SHOCK / BURIED STORY / CONTRARIAN / PERSONAL STAKE / TIMING EDGE
CTAs:
- "No name. Just signal. Follow to stay ahead of Korean markets."
- "Most Korea coverage is 12 hours late. Mine isn't. Follow."
- "Korea's crypto traders are 2 weeks ahead of global retail. I track them. Follow."

RULES:
- NEVER start with "South Korea" / "Korea's"
- Body ≤ 270 characters
- Hook needs number OR contradiction
- Use "you". One opinion. No hedging.

Respond in JSON ONLY:
{
  "hook": "...",
  "body": "... (≤ 270 chars)",
  "thread_continuation": null,
  "category_suggestion": "politics|policy|economy|society|crypto|kpop_culture|evergreen|community",
  "content_pillar": "economy|crypto|geopolitics|community",
  "optimal_post_time": "09:00 EST",
  "tone_notes": "hook type, opinion, angle"
}"""


def _strip_json(text: str) -> str:
    text = re.sub(r"^```(?:json)?\s*", "", text.strip())
    return re.sub(r"\s*```$", "", text).strip()


class TogetherDraftWriter(BaseDraftWriter):
    """
    Together AI를 사용한 초안 작성기.
    오픈소스 최대 모델 (Llama 3.1 405B / Qwen 2.5 72B) 접근.
    민감한 콘텐츠에 더 유연한 처리 가능.
    """

    def __init__(self, preferred_model: str | None = None):
        self.preferred_model = preferred_model or TOGETHER_MODELS[0]

    async def generate_draft(
        self,
        title: str,
        source_text: str,
        language: str = "en",
        source_type: str = "manual",
    ) -> DraftResult:
        logger.info(f"[Together DraftWriter] 초안 생성: '{title[:50]}'")

        community_note = ""
        if source_type == "community_input":
            community_note = (
                "\n\n[COMMUNITY MODE: Frame as 'In Korean forums...' "
                "— sentiment only, no usernames or direct quotes]"
            )

        user_msg = (
            f"Write an X post draft.\nTitle: {title}\n"
            f"Source:\n{source_text[:2000]}\nLanguage: {language}"
            f"{community_note}\nJSON only."
        )

        models_to_try = [self.preferred_model] + [
            m for m in TOGETHER_MODELS if m != self.preferred_model
        ]

        for model in models_to_try:
            try:
                async with httpx.AsyncClient(timeout=60) as client:
                    resp = await client.post(
                        TOGETHER_API_URL,
                        headers={
                            "Authorization": f"Bearer {settings.together_api_key}",
                            "Content-Type": "application/json",
                        },
                        json={
                            "model": model,
                            "messages": [
                                {"role": "system", "content": _SYSTEM_PROMPT},
                                {"role": "user", "content": user_msg},
                            ],
                            "temperature": 0.7,
                            "max_tokens": 512,
                        },
                    )
                    resp.raise_for_status()
                    raw = resp.json()["choices"][0]["message"]["content"]
                    data = json.loads(_strip_json(raw))

                    logger.info(f"[Together DraftWriter] 성공 ({model.split('/')[-1]})")
                    return DraftResult(
                        hook=data.get("hook", title),
                        body=data.get("body", ""),
                        thread_continuation=data.get("thread_continuation"),
                        category_suggestion=data.get("category_suggestion", "evergreen"),
                        tone_notes=data.get("tone_notes", ""),
                    )
            except Exception as e:
                logger.warning(f"[Together DraftWriter] {model.split('/')[-1]} 실패: {e}")
                continue

        raise RuntimeError("Together DraftWriter: 모든 모델 실패")
