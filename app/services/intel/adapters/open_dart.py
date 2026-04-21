"""
Open DART (한국 전자공시) adapter.
  https://opendart.fss.or.kr/guide/detail.do?apiGrp=DS001&apiId=DS001
  endpoint: /api/list.json
  응답 list[dict] — key: corp_name, report_nm, rcept_dt, rcept_no …
"""

from __future__ import annotations

from datetime import datetime

from app.config import settings
from app.services.intel.adapters.base import BaseAdapter
from app.services.intel.schema import IntelCategory, NormalizedIntelItem


class OpenDartAdapter(BaseAdapter):
    name = "open_dart"
    source_type = "filing"
    default_category = IntelCategory.KOREA_FILINGS

    ENDPOINT = "https://opendart.fss.or.kr/api/list.json"

    @property
    def enabled(self) -> bool:
        return settings.has_open_dart

    async def fetch(self, limit: int = 50) -> list[NormalizedIntelItem]:
        if not self.enabled:
            return []
        data = await self._http_get(
            self.ENDPOINT,
            params={
                "crtfc_key": settings.open_dart_api_key,
                "page_count": min(max(limit, 1), 100),
            },
        )
        if not isinstance(data, dict):
            return []
        raw_list = data.get("list") or []
        out: list[NormalizedIntelItem] = []
        for raw in raw_list:
            try:
                corp = (raw.get("corp_name") or "").strip()
                title = (raw.get("report_nm") or "").strip()
                rcept_dt = (raw.get("rcept_dt") or "").strip()  # YYYYMMDD
                rcept_no = (raw.get("rcept_no") or "").strip()
                pub = _parse_yyyymmdd(rcept_dt)
                url = (
                    f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}"
                    if rcept_no else None
                )
                if not title:
                    continue
                out.append(NormalizedIntelItem(
                    source=self.name,
                    source_type=self.source_type,
                    title=title[:500],
                    summary=f"{corp} — {title}"[:400],
                    url=url,
                    published_at=pub,
                    entity=corp or None,
                    category=self.default_category,
                    raw_payload=raw,
                ))
            except Exception:
                continue
        return out


def _parse_yyyymmdd(s: str) -> datetime | None:
    if not s or len(s) != 8 or not s.isdigit():
        return None
    try:
        return datetime.strptime(s, "%Y%m%d")
    except Exception:
        return None
