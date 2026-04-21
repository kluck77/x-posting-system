"""
US Congress API (법안) adapter.
  https://api.congress.gov/
  endpoint: /v3/bill?api_key=...&format=json
  응답: {bills: [{number, title, latestAction:{text,actionDate}, congress,
                  type, url}]}
"""

from __future__ import annotations

from datetime import datetime

from app.config import settings
from app.services.intel.adapters.base import BaseAdapter
from app.services.intel.schema import IntelCategory, NormalizedIntelItem


class CongressAdapter(BaseAdapter):
    name = "congress"
    source_type = "bill"
    default_category = IntelCategory.US_POLICY_BILLS

    ENDPOINT = "https://api.congress.gov/v3/bill"

    @property
    def enabled(self) -> bool:
        return settings.has_congress

    async def fetch(self, limit: int = 50) -> list[NormalizedIntelItem]:
        if not self.enabled:
            return []
        data = await self._http_get(
            self.ENDPOINT,
            params={
                "api_key": settings.congress_api_key,
                "format": "json",
                "limit": min(max(limit, 1), 250),
            },
        )
        if not isinstance(data, dict):
            return []
        bills = data.get("bills") or []
        out: list[NormalizedIntelItem] = []
        for raw in bills:
            try:
                title = (raw.get("title") or "").strip()
                number = str(raw.get("number") or "").strip()
                btype = (raw.get("type") or "").strip()
                bill_id = f"{btype} {number}".strip() or None
                latest = raw.get("latestAction") or {}
                latest_text = (latest.get("text") or "").strip()
                action_date = (latest.get("actionDate") or "").strip()
                pub = _parse_iso_date(action_date)
                url = raw.get("url")
                if not title:
                    continue
                out.append(NormalizedIntelItem(
                    source=self.name,
                    source_type=self.source_type,
                    title=title[:500],
                    summary=(f"{bill_id}: {latest_text}" if bill_id else latest_text)[:400],
                    url=url,
                    published_at=pub,
                    entity=bill_id,
                    category=self.default_category,
                    raw_payload=raw,
                ))
            except Exception:
                continue
        return out


def _parse_iso_date(s: str) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s[:10])
    except Exception:
        return None
