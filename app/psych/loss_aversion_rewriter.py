"""손실회피 언어 변환기.

Kahneman λ=2.25 기반 — 이득 프레임을 손실 프레임으로 전환.
정규식 사전 치환(80%) + Haiku 보정(20%).
직접 투자 조언 생성 절대 금지 (자본시장법).
"""
from __future__ import annotations

import json
import logging
import re

import httpx

from app.config import settings
from app.services.prompt_cache import wrap_anthropic_cache

logger = logging.getLogger(__name__)

# 정규식 사전 치환 (순서 중요, 위에서부터 매칭)
LOSS_AVERSION_DICT: list[tuple[re.Pattern, str]] = [
    # 상승/호재 → 선점 기회 프레임
    (re.compile(r"상승\s*(가능|가능성|전망)"),     "선점 신호"),
    (re.compile(r"호재\s*반영"),                  "선점 구간 진입"),
    (re.compile(r"긍정적\s*흐름"),                "흐름 바뀌기 전 마지막 구간"),
    (re.compile(r"추가\s*상승\s*기대"),           "이 구간 놓치면 다음 진입점은 더 높다"),

    # 관망/대기 → 기회손실 프레임
    (re.compile(r"관망세\s*(지속|유지|이어)"),    "방관하는 사이 구조가 바뀐다"),
    (re.compile(r"지켜봐야\s*(할|한다|됩니다)"),  "확인하고 들어가면 늦는 신호가 있다"),

    # 리스크 완화 → 구체 위험 표현
    (re.compile(r"일부\s*우려\s*(있|제기)"),      "무시하면 나중에 후회할 신호"),
    (re.compile(r"변동성\s*확대\s*우려"),         "포지션 재검토 안 하면 물릴 수 있는 구간"),

    # 직접 투자 조언 삭제 (Hard Rule 우회 차단)
    (re.compile(r"매수\s*(권장|추천|타이밍|적기)"), ""),
    (re.compile(r"지금\s*사야\s*(할|합니다|됩니다)"), ""),
    (re.compile(r"(즉시|바로)\s*매수"),           ""),
]

HAIKU_SYSTEM = """당신은 한국어 금융 텍스트의 손실회피 언어 변환기입니다.
아래 규칙을 따르세요:

1. 이득 프레임 → 손실 프레임으로 자연스럽게 변환
2. 직접 투자 조언(매수/매도/지금 사세요) 절대 생성 금지
3. 자본시장법 위반 표현 금지
4. 원문 의미 보존, 문체 유지
5. 변환이 어색하면 원문 그대로 반환

JSON만 반환:
{
  "rewritten": "변환된 텍스트",
  "changed": true/false,
  "changes_count": 숫자
}"""


def _dict_rewrite(text: str) -> tuple[str, int]:
    """정규식 사전 치환. (결과, 변환 횟수) 반환."""
    count = 0
    for pattern, replacement in LOSS_AVERSION_DICT:
        new_text, n = pattern.subn(replacement, text)
        if n > 0:
            text = new_text
            count += n
    return text, count


async def rewrite(text: str) -> dict:
    """
    반환값: {rewritten, changed, changes_count, source}
    """
    if not text:
        return {"rewritten": "", "changed": False, "changes_count": 0, "source": "empty"}

    # 1. 정규식 사전 치환
    rewritten, count = _dict_rewrite(text)
    if count > 0:
        logger.debug(f"[LossAversion] 사전 치환 {count}건")
        return {
            "rewritten":     rewritten,
            "changed":       True,
            "changes_count": count,
            "source":        "dict",
        }

    # 2. 트리거 단어 없으면 Haiku 호출 안 함 (20% 케이스만)
    trigger_words = ["가능성", "기대", "전망", "상승", "호재", "관망"]
    if not any(w in text for w in trigger_words):
        return {
            "rewritten":     text,
            "changed":       False,
            "changes_count": 0,
            "source":        "skip",
        }

    return await _haiku_rewrite(text)


async def _haiku_rewrite(text: str) -> dict:
    api_key = settings.anthropic_api_key
    if not api_key:
        return {"rewritten": text, "changed": False,
                "changes_count": 0, "source": "no_key"}

    try:
        payload = {
            "model":      "claude-haiku-4-5-20251001",
            "max_tokens": 800,
            "system":     wrap_anthropic_cache(HAIKU_SYSTEM),
            "messages":   [{"role": "user", "content": text}],
            "temperature": 0.3,
        }
        async with httpx.AsyncClient(timeout=20) as client:
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
            data["source"] = "haiku"
            data.setdefault("rewritten", text)
            data.setdefault("changed", False)
            try:
                data["changes_count"] = int(data.get("changes_count", 0))
            except Exception:
                data["changes_count"] = 0
            return data
    except Exception as e:
        logger.warning(f"[LossAversion] Haiku 실패: {e}")
        return {"rewritten": text, "changed": False,
                "changes_count": 0, "source": "error"}
