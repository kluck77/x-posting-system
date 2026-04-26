"""리플 유도 질문 생성기.

포스트 마지막에 답글 유도 질문 1개 추가.
X 알고리즘 reply_engaged_by_author=75 (like의 150배) 활성화 의도.

3 타입 (tone 매핑):
  DEBATE       — anxiety / anger
  PREDICTION   — neutral / awe
  EXPERIENCE   — excitement

블랙리스트 문구 금지 (의견 주세요 / 댓글 / 어떻게 보시나요 등).
"""
from __future__ import annotations

import json
import logging

import httpx

from app.config import settings
from app.services.prompt_cache import wrap_anthropic_cache

logger = logging.getLogger(__name__)

BLACKLIST = [
    "어떻게 보시나요",
    "의견 주세요",
    "댓글 남겨주세요",
    "생각을 공유해주세요",
    "여러분의 의견은",
]

REPLY_HOOK_SYSTEM = """당신은 한국어 X 포스트에 리플을 유도하는 질문을 생성합니다.

3가지 타입 중 tone에 맞는 것 1개만 생성:
- DEBATE: 두 입장 중 선택 (anxiety/anger 톤에 적합)
  예: "A파냐 B파냐 — 어느 쪽이 맞다고 보나"
- PREDICTION: 수치+기간 예측 요청 (neutral/awe 톤에 적합)
  예: "3개월 후 BTC는 얼마?"
- EXPERIENCE: 구체 경험 요청 (excitement 톤에 적합)
  예: "지금 포지션 어떻게 잡고 있나"

절대 금지: 어떻게 보시나요/의견 주세요/댓글 남겨주세요/생각을 공유해주세요

JSON만 반환:
{
  "hook": "질문 텍스트",
  "type": "DEBATE|PREDICTION|EXPERIENCE"
}"""

TONE_TO_TYPE = {
    "anxiety":    "DEBATE",
    "anger":      "DEBATE",
    "neutral":    "PREDICTION",
    "awe":        "PREDICTION",
    "excitement": "EXPERIENCE",
}


async def generate(post_text: str, tone: str = "neutral") -> dict:
    """
    반환값: {hook, type, appended_text}
    hook 이 빈 문자열이면 생성 실패/블랙리스트 — post_text 그대로.
    """
    if not post_text:
        return {"hook": "", "type": "", "appended_text": ""}

    # 블랙리스트 체크 (본문에 이미 있으면 중복 금지)
    for bl in BLACKLIST:
        if bl in post_text:
            logger.debug("[ReplyHook] 블랙리스트 감지, 스킵")
            return {"hook": "", "type": "", "appended_text": post_text}

    preferred_type = TONE_TO_TYPE.get(tone, "PREDICTION")

    api_key = settings.anthropic_api_key
    if not api_key:
        return {"hook": "", "type": "", "appended_text": post_text}

    try:
        payload = {
            "model":      "claude-haiku-4-5-20251001",
            "max_tokens": 150,
            "system":     wrap_anthropic_cache(REPLY_HOOK_SYSTEM),
            "messages": [
                {
                    "role": "user",
                    "content": (
                        f"tone: {tone}\n"
                        f"preferred_type: {preferred_type}\n\n"
                        f"포스트:\n{post_text[:400]}"
                    ),
                }
            ],
            "temperature": 0.5,
        }
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key":        api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type":     "application/json",
                    "anthropic-beta":   "prompt-caching-2024-07-31",
                },
                json=payload,
            )
            resp.raise_for_status()
            raw = resp.json()["content"][0]["text"].strip()
            raw = raw.strip("```json").strip("```").strip()
            data = json.loads(raw)
            hook = str(data.get("hook", "") or "").strip()

            # 블랙리스트 재검사
            if any(bl in hook for bl in BLACKLIST):
                logger.warning("[ReplyHook] 블랙리스트 포함 결과 폐기")
                return {"hook": "", "type": "", "appended_text": post_text}

            appended = f"{post_text}\n\n{hook}" if hook else post_text
            logger.info(f"[ReplyHook] type={data.get('type')} hook={hook[:40]}")
            return {
                "hook":          hook,
                "type":          data.get("type", ""),
                "appended_text": appended,
            }
    except Exception as e:
        logger.warning(f"[ReplyHook] 실패: {e}")
        return {"hook": "", "type": "", "appended_text": post_text}
