"""호기심 갭 삽입기.

Mystery / Prediction / Contradiction 3 패턴.
config.curiosity_gap_enabled=False (기본) 시 no-op.

스펙의 openai SDK import 대신 httpx + OpenAI API 직접 호출로 보정
(프로젝트 전역 패턴과 일치). api_key 도 openai_api_key 로 보정.
"""
from __future__ import annotations

import json
import logging
import re

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

OPENAI_API_URL = "https://api.openai.com/v1/chat/completions"
OPENAI_MODEL = "gpt-4o-mini"

FOLLOWUP_PATTERN = re.compile(r"하지만|그러나|반면|AND|BUT|호재.*악재|악재.*호재")
NUMBER_PATTERN = re.compile(r"\d+[\d,\.]*")

CURIOSITY_SYSTEM = """당신은 한국어 X 포스트에 호기심 갭을 삽입하는 편집자입니다.

3가지 패턴 중 1개만 적용:

MYSTERY: 핵심 사실 하나를 힌트만 남기고 생략
  예: "숫자는 깔끔하다. 하지만 진짜 신호는 다른 데 있다."

PREDICTION: 조건+기간 예측 형태로 훅 생성
  예: "2주 안에 이 레벨이 테스트된다. 깨지면 시나리오가 바뀐다."

CONTRADICTION: 두 상반된 사실을 병치
  예: "ETF는 유입인데 거래소는 유출이다. 둘 중 하나가 틀렸다."

규칙:
- 동일 스레드 안에서 반드시 완결 (낚시 금지)
- 14자 이내 한 문장
- 포스트 끝 또는 두 번째 줄에 삽입

JSON만 반환:
{
  "gap_text": "삽입할 문장",
  "pattern": "MYSTERY|PREDICTION|CONTRADICTION",
  "insert_position": "end|second_line"
}"""


def _auto_pick_pattern(text: str) -> str:
    if FOLLOWUP_PATTERN.search(text):
        return "CONTRADICTION"
    numbers = NUMBER_PATTERN.findall(text)
    if len(numbers) >= 3:
        return "MYSTERY"
    return "PREDICTION"


async def inject(post_text: str) -> dict:
    """
    반환값: {injected_text, gap_text, pattern, changed}
    curiosity_gap_enabled=False 이면 no-op.
    """
    if not getattr(settings, "curiosity_gap_enabled", False):
        return {
            "injected_text": post_text,
            "gap_text":      "",
            "pattern":       "",
            "changed":       False,
        }
    if not post_text:
        return {
            "injected_text": post_text,
            "gap_text":      "",
            "pattern":       "",
            "changed":       False,
        }

    api_key = settings.openai_api_key
    if not api_key:
        return {
            "injected_text": post_text,
            "gap_text":      "",
            "pattern":       "",
            "changed":       False,
        }

    preferred = _auto_pick_pattern(post_text)

    payload = {
        "model": OPENAI_MODEL,
        "messages": [
            {"role": "system", "content": CURIOSITY_SYSTEM},
            {
                "role": "user",
                "content": (
                    f"preferred_pattern: {preferred}\n\n"
                    f"포스트:\n{post_text[:600]}"
                ),
            },
        ],
        "temperature": 0.6,
        "max_tokens":  200,
        "response_format": {"type": "json_object"},
    }

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                OPENAI_API_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type":  "application/json",
                },
                json=payload,
            )
            resp.raise_for_status()
            raw = resp.json()["choices"][0]["message"]["content"].strip()
            data = json.loads(raw)
    except Exception as e:
        logger.warning(f"[CuriosityGap] 실패: {e}")
        return {
            "injected_text": post_text,
            "gap_text":      "",
            "pattern":       "",
            "changed":       False,
        }

    gap_text = str(data.get("gap_text", "") or "").strip()
    position = str(data.get("insert_position", "end") or "end")
    if not gap_text:
        return {
            "injected_text": post_text,
            "gap_text":      "",
            "pattern":       "",
            "changed":       False,
        }

    if position == "second_line":
        lines = post_text.split("\n")
        if len(lines) >= 2:
            lines.insert(1, gap_text)
            injected = "\n".join(lines)
        else:
            injected = f"{post_text}\n{gap_text}"
    else:
        injected = f"{post_text}\n\n{gap_text}"

    logger.info(
        f"[CuriosityGap] pattern={data.get('pattern')} gap={gap_text[:30]}"
    )
    return {
        "injected_text": injected,
        "gap_text":      gap_text,
        "pattern":       str(data.get("pattern", preferred) or preferred),
        "changed":       True,
    }
