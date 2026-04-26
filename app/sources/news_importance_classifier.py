"""뉴스 중요도 분류기.

Gemini 2.5 Flash 로 뉴스를 importance(0-10) / category / decay_hours 로 분류.
실패 시 generic fallback dict 반환 (파이프라인 중단 없음).
"""
from __future__ import annotations

import json
import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "gemini-2.5-flash-preview:generateContent"
)

CLASSIFIER_SYSTEM = """당신은 한국 크립토·매크로·정책 뉴스 중요도 판단 AI입니다.
아래 기준으로 뉴스를 평가해서 JSON만 반환하세요.

중요도(0-10):
9-10: 시장 구조 변화, 규제 확정, 대형 해킹, FOMC
7-8: 주요 온체인 데이터, 기관 매매, 정책 발의
5-6: 일반 시장 현황, 기업 소식
3-4: 분석·의견 기사
0-2: 광고성, 반복, 오래된 내용

카테고리: regulation | hack | price_action | product | macro | opinion

JSON 형식:
{
  "importance": 0-10,
  "category": "카테고리",
  "decay_hours": 숫자,
  "reasoning_ko": "판단 이유 한 줄"
}
JSON만 반환. 다른 텍스트 금지."""


def _default_fallback(reason: str) -> dict:
    return {
        "importance":   5,
        "category":     "opinion",
        "decay_hours":  12,
        "reasoning_ko": reason,
    }


async def classify_news(title: str, body: str = "") -> dict:
    api_key = settings.gemini_api_key
    if not api_key:
        return _default_fallback("API 키 없음")

    payload = {
        "systemInstruction": {"parts": [{"text": CLASSIFIER_SYSTEM}]},
        "contents": [
            {"parts": [{"text": f"제목: {title}\n\n본문: {(body or '')[:500]}"}]}
        ],
        "generationConfig": {
            "temperature":     0.1,
            "maxOutputTokens": 200,
        },
    }

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{GEMINI_URL}?key={api_key}",
                json=payload,
            )
            resp.raise_for_status()
            text = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
            text = text.strip().strip("```json").strip("```").strip()
            data = json.loads(text)
            # 안전 캐스팅 (Gemini 가 가끔 string 으로 숫자 줌)
            try:
                data["importance"] = int(data.get("importance", 5))
            except Exception:
                data["importance"] = 5
            try:
                data["decay_hours"] = int(data.get("decay_hours", 12))
            except Exception:
                data["decay_hours"] = 12
            data.setdefault("category", "opinion")
            data.setdefault("reasoning_ko", "")
            return data
    except Exception as e:
        logger.warning(f"[NewsClassifier] 실패 (기본값 반환): {e}")
        return _default_fallback("분류 실패")
