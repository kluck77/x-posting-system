"""
CoinGecko adapter — Phase 2 stub.
Phase 1 에서는 항상 enabled=False 고정. fetch() 는 no-op.
"""

from app.services.intel.adapters.base import BaseAdapter
from app.services.intel.schema import IntelCategory, NormalizedIntelItem


class CoinGeckoAdapter(BaseAdapter):
    name = "coingecko"
    source_type = "asset_context"
    default_category = IntelCategory.ASSET_CONTEXT

    @property
    def enabled(self) -> bool:
        return False  # Phase 2 에서 활성화

    async def fetch(self, limit: int = 50) -> list[NormalizedIntelItem]:
        return []
