"""
Intel dedup — content_hash 계산
================================
sha256 (source|url|title|published_at) 의 64자 hex.
동일 adapter 에서 재발행되는 동일 항목을 DB unique 제약으로 걸러낸다.
"""

import hashlib
from datetime import datetime
from typing import Optional


def compute_content_hash(
    source: str,
    url: Optional[str],
    title: str,
    published_at: Optional[datetime],
) -> str:
    """결정적 해시 — 같은 입력이면 같은 해시."""
    url_part = (url or "").strip()
    title_part = (title or "").strip()
    ts_part = published_at.isoformat() if published_at else ""
    raw = f"{source}|{url_part}|{title_part}|{ts_part}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()
