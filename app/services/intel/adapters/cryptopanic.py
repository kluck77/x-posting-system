"""
CryptoPanic adapter.
  https://cryptopanic.com/developers/api/
  endpoint: /api/v1/posts/?auth_token=...&public=true
  응답: {results: [{title, url, published_at, currencies:[{code,title,slug}],
                    source:{title,domain}}]}
"""

from __future__ import annotations

from datetime import datetime

from app.config import settings
from app.services.intel.adapters.base import BaseAdapter
from app.services.intel.schema import IntelCategory, NormalizedIntelItem


class CryptoPanicAdapter(BaseAdapter):
    name = "cryptopanic"
    source_type = "crypto_news"
    default_category = IntelCategory.CRYPTO_STREAM

    ENDPOINT = "https://cryptopanic.com/api/v1/posts/"

    @property
    def enabled(self) -> bool:
        return settings.has_cryptopanic

    async def fetch(self, limit: int = 50) -> list[NormalizedIntelItem]:
        if not self.enabled:
            return []
        data = await self._http_get(
            self.ENDPOINT,
            params={
                "auth_token": settings.cryptopanic_api_key,
                "public": "true",
            },
        )
        if not isinstance(data, dict):
            return []
        results = data.get("results") or []
        out: list[NormalizedIntelItem] = []
        for raw in results[:limit]:
            try:
                title = (raw.get("title") or "").strip()
                url = raw.get("url")
                pub = _parse_iso(raw.get("published_at"))
                currencies = raw.get("currencies") or []
                entity = None
                if currencies and isinstance(currencies, list):
                    entity = (currencies[0] or {}).get("code") or None
                source_info = raw.get("source") or {}
                src_title = (source_info.get("title") or "").strip()
                if not title:
                    continue
                out.append(NormalizedIntelItem(
                    source=self.name,
                    source_type=self.source_type,
                    title=title[:500],
                    summary=(f"{src_title}" if src_title else "")[:400],
                    url=url,
                    published_at=pub,
                    entity=entity,
                    category=self.default_category,
                    raw_payload=raw,
                ))
            except Exception:
                continue
        return out


def _parse_iso(s) -> datetime | None:
    if not s or not isinstance(s, str):
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None
