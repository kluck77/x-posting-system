"""최적 포스팅 시간 예측기.

현재: 규칙 기반 시간대 추천 (데이터 없음, 기본).
config.optimal_timing_enabled=True 로 활성화 시 90일 승인 DB 에서
시간대별 빈도 계산 → 상위 N개 추천.
"""
from __future__ import annotations

import logging
import re
import sqlite3
import time

from app.config import settings

logger = logging.getLogger(__name__)

# 규칙 기반 기본 시간대 (KST)
RULE_BASED_SLOTS: dict[str, list[dict]] = {
    "crypto": [
        {"hour":  8, "minute": 30, "reason": "아시아 장 오픈"},
        {"hour": 21, "minute":  0, "reason": "미국 프리마켓"},
        {"hour": 22, "minute": 30, "reason": "미국 장 오픈"},
    ],
    "macro": [
        {"hour":  9, "minute":  0, "reason": "국내 장 오픈"},
        {"hour": 21, "minute": 30, "reason": "미국 지표 발표"},
    ],
    "regulation": [
        {"hour":  9, "minute":  0, "reason": "정규 업무 시작"},
        {"hour": 18, "minute":  0, "reason": "저녁 뉴스 시간"},
    ],
}

DEFAULT_SLOTS = [
    {"hour":  8, "minute": 30, "reason": "아침 출근"},
    {"hour": 12, "minute":  0, "reason": "점심"},
    {"hour": 21, "minute":  0, "reason": "저녁"},
]


def _sqlite_path() -> str:
    url = settings.database_url or ""
    m = re.match(r"sqlite:///(.+)", url)
    return m.group(1) if m else "./x_poster.db"


def get_optimal_slots(
    category: str = "crypto",
    n: int = 3,
    db_path: str | None = None,
) -> list[dict]:
    """최적 시간대 N개 반환.

    optimal_timing_enabled=False 이면 규칙 기반 반환.
    True 이면 DB 기반 조회 시도, 데이터 부족/오류 시 규칙 기반 fallback.
    """
    if not getattr(settings, "optimal_timing_enabled", False):
        slots = RULE_BASED_SLOTS.get(category, DEFAULT_SLOTS)
        return slots[:n]

    path = db_path or _sqlite_path()
    try:
        conn = sqlite3.connect(path)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT strftime('%H', datetime(created_at, 'unixepoch', 'localtime')) AS hour,
                   COUNT(*) as cnt
            FROM telegram_queue
            WHERE status = 'approved'
              AND created_at > ?
            GROUP BY hour
            ORDER BY cnt DESC
            LIMIT ?
        """, (time.time() - 90 * 86400, n))
        rows = cursor.fetchall()
        conn.close()
        if not rows:
            return RULE_BASED_SLOTS.get(category, DEFAULT_SLOTS)[:n]
        return [
            {
                "hour":   int(r[0]),
                "minute": 0,
                "reason": f"데이터 기반 (승인 {r[1]}건)",
            }
            for r in rows
        ]
    except Exception as e:
        logger.warning(f"[OptimalTiming] DB 조회 실패 (규칙 기반 fallback): {e}")
        return RULE_BASED_SLOTS.get(category, DEFAULT_SLOTS)[:n]


def format_timing_hint(category: str = "crypto") -> str:
    """텔레그램 카드용 시간 힌트. 상위 2개 slot."""
    slots = get_optimal_slots(category, n=2)
    if not slots:
        return ""
    slot_str = " / ".join(
        f"{s['hour']:02d}:{s.get('minute', 0):02d}"
        for s in slots
    )
    return f"⏰ 추천 발행: {slot_str} KST"
