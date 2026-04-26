"""
Finnhub (마켓/기업 뉴스) adapter.
  https://finnhub.io/docs/api/market-news
  endpoint: /api/v1/news?category=general&token=...
  응답: [{headline, summary, url, datetime(epoch), related, source, image}]
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.config import settings
from app.services.intel.adapters.base import BaseAdapter
from app.services.intel.schema import IntelCategory, NormalizedIntelItem


class FinnhubAdapter(BaseAdapter):
    name = "finnhub"
    source_type = "market_news"
    default_category = IntelCategory.MARKET_COMPANY

    ENDPOINT = "https://finnhub.io/api/v1/news"

    @property
    def enabled(self) -> bool:
        return settings.has_finnhub

    async def fetch(self, limit: int = 50) -> list[NormalizedIntelItem]:
        if not self.enabled:
            return []
        data = await self._http_get(
            self.ENDPOINT,
            params={"category": "general", "token": settings.finnhub_api_key},
        )
        if not isinstance(data, list):
            return []
        out: list[NormalizedIntelItem] = []
        for raw in data[:limit]:
            try:
                title = (raw.get("headline") or "").strip()
                summary = (raw.get("summary") or "").strip()
                url = raw.get("url")
                ts = raw.get("datetime")
                pub = _parse_epoch(ts)
                related = (raw.get("related") or "").strip()
                entity = related.split(",")[0].strip() if related else None
                if not title:
                    continue
                out.append(NormalizedIntelItem(
                    source=self.name,
                    source_type=self.source_type,
                    title=title[:500],
                    summary=summary[:400],
                    url=url,
                    published_at=pub,
                    entity=entity or None,
                    category=self.default_category,
                    raw_payload=raw,
                ))
            except Exception:
                continue
        return out


def _parse_epoch(ts) -> datetime | None:
    try:
        if ts is None:
            return None
        return datetime.fromtimestamp(int(ts), tz=timezone.utc)
    except Exception:
        return None
