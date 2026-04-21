"""
Intel 정규화 스키마
====================
모든 adapter 는 외부 응답을 NormalizedIntelItem 리스트로 변환해 반환한다.
UI 카드에 노출되는 compact 필드 + DB 저장용 raw_payload 로 분리한다.
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class IntelCategory(str, enum.Enum):
    """대시보드 카드 카테고리 (6종)."""
    KOREA_FILINGS    = "korea_filings"
    US_POLICY_BILLS  = "us_policy_bills"
    MARKET_COMPANY   = "market_company"
    CRYPTO_STREAM    = "crypto_stream"
    MACRO_POLICY     = "macro_policy"
    ASSET_CONTEXT    = "asset_context"


class NormalizedIntelItem(BaseModel):
    """adapter 가 반환하는 정규화 항목."""

    source: str                                    # "open_dart" 등 adapter.name
    source_type: str                               # "filing" / "bill" / "market_news" / "crypto_news"
    title: str
    summary: str = ""                              # compact, UI 노출
    url: Optional[str] = None
    published_at: Optional[datetime] = None
    entity: Optional[str] = None
    category: IntelCategory
    content_hash: str = ""                         # collect 단계에서 채움
    raw_payload: dict[str, Any] = Field(default_factory=dict)  # UI 비노출

    model_config = {"arbitrary_types_allowed": True}
