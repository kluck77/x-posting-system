"""뉴스 신선도 필터.

기본 6h, 후속 보도 24h, importance≥9 매크로 48h.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

FOLLOWUP_PATTERNS = re.compile(
    r"이후\s*\d+\s*(시간|일)|후속|여파|영향|파장|반응",
    re.IGNORECASE,
)


def get_decay_hours(
    category: str,
    importance: int,
    title: str,
    body: str = "",
) -> int:
    text = f"{title} {body}"

    # 후속 보도 감지
    if FOLLOWUP_PATTERNS.search(text):
        return 24

    # 카테고리별 기본값
    base = {
        "regulation":   48,
        "hack":         24,
        "price_action": 6,
        "product":      12,
        "macro":        24,
        "opinion":      3,
    }.get(category, 12)

    # importance 9 이상 매크로는 48h
    if importance >= 9 and category == "macro":
        return 48

    return base


def is_fresh(
    published_at: datetime,
    category: str,
    importance: int,
    title: str,
    body: str = "",
) -> bool:
    now = datetime.now(timezone.utc)
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=timezone.utc)
    age_h = (now - published_at).total_seconds() / 3600
    decay_h = get_decay_hours(category, importance, title, body)
    return age_h <= decay_h
