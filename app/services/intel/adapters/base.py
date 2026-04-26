"""
BaseAdapter — Intel 소스 공통 인터페이스
=========================================
- name / source_type / default_category 3 개 클래스 속성
- enabled 는 키 보유 여부 기반 (settings.has_<name>)
- fetch(limit) 는 NormalizedIntelItem 리스트 반환. 네트워크/파싱 에러는
  내부에서 삼키고 빈 리스트 반환 (fail-soft).
- _http_get 은 공통 httpx 헬퍼
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

from app.services.intel.schema import IntelCategory, NormalizedIntelItem

logger = logging.getLogger(__name__)


class BaseAdapter:
    # 서브클래스에서 override
    name: str = "base"
    source_type: str = "unknown"
    default_category: IntelCategory = IntelCategory.MACRO_POLICY

    # 서브클래스에서 override — 키 보유 여부
    @property
    def enabled(self) -> bool:
        return False

    async def fetch(self, limit: int = 50) -> list[NormalizedIntelItem]:
        """서브클래스에서 구현. 기본은 no-op."""
        return []

    async def _http_get(
        self,
        url: str,
        params: Optional[dict[str, Any]] = None,
        headers: Optional[dict[str, str]] = None,
        timeout: float = 10.0,
    ) -> Optional[dict[str, Any]]:
        """
        fail-soft JSON GET. 네트워크/파싱 에러는 None 반환.
        """
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.get(url, params=params, headers=headers)
                resp.raise_for_status()
                return resp.json()
        except Exception as e:
            logger.warning(
                "[intel:%s] fetch failed (fail-soft): %s", self.name, e
            )
            return None
