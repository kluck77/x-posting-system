"""뉴스 타이밍 라우터.

속보  → BYPASS_RING (즉시 텔레그램 알림)
중요  → NEXT_RING  (다음 링 슬롯)
보통  → SKIP       (건너뜀)
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

BREAKING_PATTERN = re.compile(
    r"속보|긴급|BREAKING|해킹|상장폐지|파산|체포|긴급회의",
    re.IGNORECASE,
)


class RouteDecision(Enum):
    BYPASS_RING = "bypass_ring"
    NEXT_RING   = "next_ring"
    SKIP        = "skip"


@dataclass
class RouteResult:
    decision:           RouteDecision
    reason:             str
    deadline_minutes:   int = 0


def route(title: str, importance: int, category: str) -> RouteResult:
    is_breaking = (
        BREAKING_PATTERN.search(title or "") is not None
        or importance >= 8
        or category == "hack"
    )

    if is_breaking:
        return RouteResult(
            decision=RouteDecision.BYPASS_RING,
            reason=f"속보 감지 (importance={importance})",
            deadline_minutes=10,
        )

    if importance >= 6:
        return RouteResult(
            decision=RouteDecision.NEXT_RING,
            reason=f"중요 뉴스 (importance={importance})",
            deadline_minutes=60,
        )

    if importance >= 4:
        return RouteResult(
            decision=RouteDecision.NEXT_RING,
            reason=f"일반 뉴스 (importance={importance})",
            deadline_minutes=240,
        )

    return RouteResult(
        decision=RouteDecision.SKIP,
        reason=f"낮은 중요도 (importance={importance})",
    )
