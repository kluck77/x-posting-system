"""Hook Variants — 초안 훅 3개 변형 생성 후 최선 선택.

3개 변형 타입:
  A. DATA_SHOCK: 숫자를 첫 7어절 안에 배치
  B. CONTRARIAN: 컨센서스 반박형
  C. FORCING: 날짜/트리거 포함 forcing function형

Claude Haiku 로 생성. 실패 시 원본 hook 반환.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


@dataclass
class HookVariants:
    original: str
    data_shock: str
    contrarian: str
    forcing: str
    selected: str
    selected_type: str
    score_reason: str


async def generate_variants(
    hook: str,
    body: str,
    frame_name: str = "",
) -> HookVariants:
    """훅 3개 변형 생성 + 최선 선택."""
    api_key = settings.anthropic_api_key
    if not api_key:
        return _fallback(hook)

    prompt = (
        f"아래 훅을 3가지 변형으로 재작성하라. 각각 28자 이내. 사실 추가 금지.\n\n"
        f"원본 훅: {hook}\n"
        f"본문 맥락: {body[:300]}\n"
        f"프레임: {frame_name}\n\n"
        f"규칙:\n"
        f"- data_shock: 숫자·금액·비율을 첫 7어절 안에. 충격 우선.\n"
        f"- contrarian: 컨센서스를 1문장에서 뒤집기. '언론은 X라 한다'가 아닌 직접 역전.\n"
        f"- forcing: 날짜·기한·트리거 포함. '이번 주' '48시간' '2027년 1월' 등.\n\n"
        f"그리고 3개 중 가장 강한 것 1개를 selected 로 선택하라.\n\n"
        f"JSON만 반환:\n"
        f'{{"data_shock":"","contrarian":"","forcing":"","selected":"data_shock|contrarian|forcing","score_reason":""}}'
    )

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-haiku-4-5-20251001",
                    "max_tokens": 400,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
            resp.raise_for_status()
            text = resp.json()["content"][0]["text"].strip()
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
                text = text.strip()
            parsed = json.loads(text)

            selected_type = parsed.get("selected", "data_shock")
            variant_map = {
                "data_shock": parsed.get("data_shock", hook),
                "contrarian": parsed.get("contrarian", hook),
                "forcing": parsed.get("forcing", hook),
            }
            selected_hook = variant_map.get(selected_type, hook)
            if not selected_hook or len(selected_hook) < 5:
                selected_hook = hook
                selected_type = "original"

            return HookVariants(
                original=hook,
                data_shock=parsed.get("data_shock", hook),
                contrarian=parsed.get("contrarian", hook),
                forcing=parsed.get("forcing", hook),
                selected=selected_hook,
                selected_type=selected_type,
                score_reason=str(parsed.get("score_reason", ""))[:200],
            )

    except Exception as e:
        logger.warning(f"[hook_variants] 생성 실패 (원본 유지): {e}")
        return _fallback(hook)


def _fallback(hook: str) -> HookVariants:
    return HookVariants(
        original=hook,
        data_shock=hook,
        contrarian=hook,
        forcing=hook,
        selected=hook,
        selected_type="original",
        score_reason="fallback",
    )
