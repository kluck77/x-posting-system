"""스테일 기사 필터.

published_at 기반 4-트랙 분류:
  FRESH  <24h   → 통과
  WARM   <72h   → 통과
  TREND  3~30d  → 1차 소스(filing/bill/enforcement)만 통과 (회고 앵커 가치)
  STALE  >30d   → discard

참조: 리서치 결과 "Stale Filter" 블록.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from app.services.intel.schema import NormalizedIntelItem

Track = Literal["FRESH", "WARM", "TREND", "STALE", "NO_DATE"]

FRESH_HOURS = 24
WARM_HOURS = 72
TREND_DAYS = 30

# 30일 지난 뉴스도 1차 소스면 회고 앵커로 통과
RETRO_ALLOWED_SOURCE_TYPES = {"filing", "bill", "enforcement", "policy"}


def _age_hours(published_at: datetime | None) -> float | None:
    """tz-safe 경과 시간 계산. None 또는 실패 시 None 반환."""
    if published_at is None:
        return None
    try:
        now = datetime.now(timezone.utc)
        if published_at.tzinfo is None:
            # naive datetime 은 UTC 로 간주
            published_at = published_at.replace(tzinfo=timezone.utc)
        delta = (now - published_at).total_seconds() / 3600.0
        return max(0.0, delta)
    except Exception:
        return None


def classify(item: NormalizedIntelItem) -> Track:
    """4-트랙 분류."""
    age_h = _age_hours(item.published_at)

    if age_h is None:
        return "NO_DATE"

    if age_h < FRESH_HOURS:
        return "FRESH"

    if age_h < WARM_HOURS:
        return "WARM"

    if age_h < TREND_DAYS * 24:
        # 3~30일: 1차 소스만 회고 앵커로 통과
        if item.source_type in RETRO_ALLOWED_SOURCE_TYPES:
            return "TREND"
        return "STALE"

    return "STALE"


def is_stale(item: NormalizedIntelItem) -> bool:
    """True 면 collect 루프에서 skip."""
    return classify(item) == "STALE"
