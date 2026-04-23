"""A/B 훅 자동 생성기.

버전 A: 손실회피 프레임 (Kahneman λ=2.25)
버전 B: 호기심 갭 프레임 (Loewenstein 1994)

config.ab_test_enabled=False (기본) 시 generate() 가 None 반환.
운영자 선택 로그는 ab_choices 테이블에 누적, 50건 이상 시 패턴 추천.
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
import time
from dataclasses import dataclass

import httpx

from app.config import settings
from app.services.prompt_cache import wrap_anthropic_cache

logger = logging.getLogger(__name__)


def _sqlite_path() -> str:
    url = settings.database_url or ""
    m = re.match(r"sqlite:///(.+)", url)
    return m.group(1) if m else "./x_poster.db"


@dataclass
class ABVariants:
    news_id:   str
    variant_a: str
    variant_b: str
    original:  str


AB_SYSTEM = """당신은 한국어 X 포스트의 첫 문장(훅)을 2가지 버전으로 생성합니다.

버전 A: 손실회피 프레임 (Kahneman λ=2.25)
- "지금 안 보면 놓치는 것", "이걸 모르면 나중에 후회"
- 투자 조언 금지, 자본시장법 준수

버전 B: 호기심 갭 프레임 (Loewenstein 1994)
- "진짜 신호는 다른 데 있다", "숫자는 깔끔한데..."
- 완결 필수 (낚시 금지)

각 버전 ≤28자. 기존 포스트 첫 문장을 교체하는 용도.

JSON만 반환:
{
  "variant_a": "손실회피 훅 텍스트",
  "variant_b": "호기심 갭 훅 텍스트"
}"""


async def generate(post_text: str, news_id: str) -> "ABVariants | None":
    """A/B 훅 2개 생성. disabled/키없음/실패 → None."""
    if not getattr(settings, "ab_test_enabled", False):
        return None
    if not post_text:
        return None
    api_key = settings.anthropic_api_key
    if not api_key:
        return None

    try:
        payload = {
            "model":      "claude-haiku-4-5-20251001",
            "max_tokens": 200,
            "system":     wrap_anthropic_cache(AB_SYSTEM),
            "messages": [{
                "role":    "user",
                "content": f"포스트 첫 문장을 2가지 버전으로:\n\n{post_text[:300]}",
            }],
            "temperature": 0.6,
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
            return ABVariants(
                news_id=news_id,
                variant_a=str(data.get("variant_a", "") or ""),
                variant_b=str(data.get("variant_b", "") or ""),
                original=post_text.split("\n")[0][:50],
            )
    except Exception as e:
        logger.warning(f"[ABVariant] 실패: {e}")
        return None


def log_choice(
    news_id:     str,
    choice:      str,           # "a" | "b" | "skip"
    tone:        str = "",
    category:    str = "",
    viral_score: int = 0,
    db_path:     str | None = None,
) -> None:
    """운영자 선택 로그 저장. 테이블 없으면 생성."""
    path = db_path or _sqlite_path()
    try:
        conn = sqlite3.connect(path)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ab_choices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                news_id TEXT,
                choice TEXT,
                tone TEXT,
                category TEXT,
                viral_score INTEGER,
                chosen_at REAL
            )
        """)
        cursor.execute("""
            INSERT INTO ab_choices
            (news_id, choice, tone, category, viral_score, chosen_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (news_id, choice, tone, category, viral_score, time.time()))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning(f"[ABVariant] log_choice 실패: {e}")


def get_recommendation(db_path: str | None = None) -> dict:
    """50건 이상 시 패턴 추천. 부족하면 status 로 알림."""
    path = db_path or _sqlite_path()
    try:
        conn = sqlite3.connect(path)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ab_choices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                news_id TEXT, choice TEXT, tone TEXT, category TEXT,
                viral_score INTEGER, chosen_at REAL
            )
        """)
        cursor.execute("SELECT COUNT(*) FROM ab_choices")
        count = cursor.fetchone()[0]
        if count < 50:
            conn.close()
            return {"status": f"데이터 부족 ({count}/50건)"}

        cursor.execute("""
            SELECT choice, tone, category, COUNT(*) as cnt
            FROM ab_choices
            WHERE choice != 'skip'
            GROUP BY choice, tone, category
            ORDER BY cnt DESC
        """)
        rows = cursor.fetchall()
        conn.close()
        return {
            "status":        "추천 가능",
            "total_choices": count,
            "top_patterns": [
                {
                    "choice":   r[0],
                    "tone":     r[1],
                    "category": r[2],
                    "count":    r[3],
                }
                for r in rows[:5]
            ],
        }
    except Exception as e:
        return {"status": f"오류: {e}"}
