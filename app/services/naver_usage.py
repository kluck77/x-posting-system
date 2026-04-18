"""
Naver API 일일 사용량 추적기
============================
search_keyword() 호출 시 카운터를 올립니다.
자정(UTC)에 자동 리셋됩니다.

Naver Open API 무료 한도: 뉴스/검색 25,000회/일
"""

import threading
from datetime import date, datetime, timezone

_lock = threading.Lock()
_today_date: date | None = None
_today_calls: int = 0

DAILY_LIMIT = 25_000


def record_call(n: int = 1) -> None:
    """API 호출 n회 기록."""
    global _today_date, _today_calls
    with _lock:
        today = datetime.now(timezone.utc).date()
        if _today_date != today:
            _today_date = today
            _today_calls = 0
        _today_calls += n


def get_today_calls() -> int:
    """오늘 총 호출 수 반환 (UTC 기준)."""
    global _today_date, _today_calls
    with _lock:
        today = datetime.now(timezone.utc).date()
        if _today_date != today:
            return 0
        return _today_calls


def get_status() -> dict:
    """대시보드용 Naver 할당량 현황."""
    used = get_today_calls()
    remaining = max(0, DAILY_LIMIT - used)
    pct = round(used / DAILY_LIMIT * 100, 1) if DAILY_LIMIT else 0
    if used == 0:
        level = "idle"
    elif pct < 50:
        level = "ok"
    elif pct < 80:
        level = "caution"
    else:
        level = "warning"
    return {
        "used_today": used,
        "daily_limit": DAILY_LIMIT,
        "remaining": remaining,
        "pct_used": pct,
        "level": level,
        "note": "추정치 — 재시작 시 리셋됩니다",
    }
