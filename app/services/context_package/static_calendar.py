"""정적 캘린더 — FOMC / CPI / BOK 금통위 (LLM 호출 없음)."""
from __future__ import annotations

from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))


# 2026 FOMC Day 2 — ET 14:00 ≈ KST D+1 03:00
FOMC_2026 = [
    "2026-04-29",
    "2026-06-17",
    "2026-07-29",
    "2026-09-16",
    "2026-10-28",
    "2026-12-09",
]

# 2026 미국 CPI — ET 08:30 ≈ KST 22:30
CPI_2026 = [
    "2026-05-13",
    "2026-06-11",
    "2026-07-15",
    "2026-08-12",
    "2026-09-11",
    "2026-10-15",
    "2026-11-13",
    "2026-12-10",
]

# 2026 한국 금통위 — KST 10:00
BOK_2026 = [
    "2026-05-29",
    "2026-07-10",
    "2026-08-28",
    "2026-10-23",
    "2026-11-27",
]


def fetch_upcoming_calendar(category: str) -> list[dict]:
    """카테고리별 향후 일정 — 최대 8건."""
    now = datetime.now(KST)
    out: list[dict] = []

    for d in FOMC_2026:
        try:
            dt_kst = (
                datetime.fromisoformat(d)
                .replace(tzinfo=timezone.utc)
                .astimezone(KST)
                + timedelta(hours=3)
            )
        except Exception:
            continue
        if dt_kst > now:
            out.append({
                "event":     "FOMC",
                "date_kst":  dt_kst.isoformat(),
                "relevance": "high" if category == "macro" else "medium",
            })

    for d in CPI_2026:
        try:
            dt_kst = datetime.fromisoformat(f"{d}T22:30:00").replace(tzinfo=KST)
        except Exception:
            continue
        if dt_kst > now:
            out.append({
                "event":     "미국 CPI",
                "date_kst":  dt_kst.isoformat(),
                "relevance": "high" if category == "macro" else "medium",
            })

    for d in BOK_2026:
        try:
            dt_kst = datetime.fromisoformat(f"{d}T10:00:00").replace(tzinfo=KST)
        except Exception:
            continue
        if dt_kst > now:
            out.append({
                "event":     "한국 금통위",
                "date_kst":  dt_kst.isoformat(),
                "relevance": "high",
            })

    return sorted(out, key=lambda x: x["date_kst"])[:8]
