"""
Intel collect — 수집 orchestration (AI 없음)
=============================================
flow:
  1. 활성 adapter 마다 async fetch(limit)
  2. content_hash 계산
  3. INSERT OR IGNORE (unique 제약 위반 시 조용히 skip)
  4. 새로 저장된 row 에 대해 filter 돌려 shortlisted / flagged_reason update
  5. 재분류된 category 가 있으면 함께 update
  6. {fetched, new, shortlisted} 반환
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.intel import IntelItem
from app.services.intel.adapters import get_all_adapters
from app.services.intel.adapters.base import BaseAdapter
from app.services.intel.dedup import compute_content_hash
from app.services.intel.filter import decide_shortlist, reclassify_category
from app.services.intel.stale_filter import classify, is_stale
from app.services.intel.schema import NormalizedIntelItem
from app.services.intel.score import (
    compose_why_flagged_human,
    compute_priority_score,
    derive_score_label,
)

logger = logging.getLogger(__name__)

# raw_payload 용량 상한 (json.dumps 이후 자름 — 수십 KB 수준이면 충분).
_RAW_PAYLOAD_MAX = 20_000

# 마지막 수집 시각 — /control/intel/status 용 관측 데이터 (키 미노출).
_last_collect_at: Optional[datetime] = None


@dataclass
class CollectStats:
    fetched: int = 0
    new: int = 0
    shortlisted: int = 0
    per_adapter: Optional[dict] = None

    def as_dict(self) -> dict:
        return {
            "fetched": self.fetched,
            "new": self.new,
            "shortlisted": self.shortlisted,
            "per_adapter": self.per_adapter or {},
        }


def _dump_raw(raw: dict) -> str:
    try:
        s = json.dumps(raw, ensure_ascii=False, default=str)
        return s[:_RAW_PAYLOAD_MAX]
    except Exception:
        return ""


async def _fetch_adapter(adapter: BaseAdapter, limit: int) -> list[NormalizedIntelItem]:
    if not adapter.enabled:
        return []
    try:
        items = await adapter.fetch(limit)
    except Exception as e:
        logger.warning("[intel:%s] fetch exception (fail-soft): %s", adapter.name, e)
        return []
    return items or []


async def collect_all(
    db: Session,
    source: Optional[str] = None,
    limit_per_source: int = 50,
) -> CollectStats:
    """
    활성 adapter 를 순회하며 IntelItem 을 적재한다.

    Args:
        source: 특정 adapter name 만 돌리고 싶을 때 (e.g. "open_dart"). None=전체.
        limit_per_source: adapter 당 최대 fetch 건수.
    """
    global _last_collect_at
    stats = CollectStats(per_adapter={})
    adapters = get_all_adapters()
    if source:
        adapters = [a for a in adapters if a.name == source]

    for adapter in adapters:
        items = await _fetch_adapter(adapter, limit_per_source)
        per = {"fetched": len(items), "new": 0, "shortlisted": 0}
        stats.fetched += len(items)

        for item in items:
            # stale filter — 30일 초과 일반 뉴스는 저장 전 discard
            if is_stale(item):
                per["stale"] = per.get("stale", 0) + 1
                stats.stale = getattr(stats, "stale", 0) + 1
                continue
            # content_hash 채우기
            item.content_hash = compute_content_hash(
                item.source, item.url, item.title, item.published_at,
            )
            # 재분류 (adapter 기본 category 위에 룰 덮어씀)
            item.category = reclassify_category(item)
            # 필터
            shortlisted, reason = decide_shortlist(item)

            # Phase 2 — 점수 / 라벨 / 사람용 이유 (순수 함수, AI 없음)
            score = compute_priority_score(item)
            label = derive_score_label(score)
            human_reason = compose_why_flagged_human(item, reason, score)

            row = IntelItem(
                source=item.source,
                source_type=item.source_type,
                title=item.title[:500],
                summary=(item.summary or "")[:2000],
                url=item.url,
                published_at=item.published_at,
                entity=(item.entity or None),
                category=item.category.value,
                content_hash=item.content_hash,
                raw_payload=_dump_raw(item.raw_payload),
                shortlisted=shortlisted,
                flagged_reason=reason or None,
                priority_score=score,
                score_label=label,
                why_flagged_human=human_reason,
                promotion_status="none",
            )
            try:
                db.add(row)
                db.commit()
                per["new"] += 1
                stats.new += 1
                if shortlisted:
                    per["shortlisted"] += 1
                    stats.shortlisted += 1
            except IntegrityError:
                # content_hash unique 위반 — 이미 저장된 동일 항목, 조용히 skip
                db.rollback()
            except Exception as e:
                db.rollback()
                logger.warning("[intel:%s] insert failed (fail-soft): %s", adapter.name, e)

        stats.per_adapter[adapter.name] = per
        if adapter.enabled:
            logger.info(
                "[intel:%s] fetched=%d new=%d shortlisted=%d",
                adapter.name, per["fetched"], per["new"], per["shortlisted"],
            )

    _last_collect_at = datetime.now(timezone.utc)
    return stats


def get_last_collect_at() -> Optional[datetime]:
    return _last_collect_at


def get_total_counts(db: Session) -> dict:
    """전체 IntelItem 개수 / shortlisted 개수 요약 (UI 관측용)."""
    try:
        total = db.execute(
            text("SELECT COUNT(*) FROM intel_items")
        ).scalar() or 0
        short = db.execute(
            text("SELECT COUNT(*) FROM intel_items WHERE shortlisted = 1")
        ).scalar() or 0
        return {"total": int(total), "shortlisted": int(short)}
    except Exception:
        return {"total": 0, "shortlisted": 0}
