"""
Crypto Intel API (Phase 1, read-only)
======================================
control_room 라우터가 이 모듈을 include 한다.
실제 경로는 /control/intel/* (control_room prefix='/control').

엔드포인트:
  POST /intel/collect                 — adapter 수집 트리거 (수 초 소요 가능)
  GET  /intel/shortlist               — shortlisted=True 카드 목록
  GET  /intel/items/{id}              — 단건 상세 (raw_payload 기본 미노출)
  GET  /intel/status                  — adapter enabled 여부 + 총계 + 최근 수집 시각

Phase 2 (본 파일 scope 밖):
  POST /intel/items/{id}/promote      — Orchestrator.full_pipeline 합류
  POST /intel/items/{id}/dismiss      — shortlist 해제
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app.db import get_db
from app.models.intel import IntelItem
from app.services.intel.collect import (
    collect_all,
    get_last_collect_at,
    get_total_counts,
)
from app.services.intel.schema import IntelCategory
from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/intel", tags=["crypto-intel"])


def _card(item: IntelItem) -> dict:
    """UI 카드 직렬화 — raw_payload 미포함, compact 필드만."""
    return {
        "id":            item.id,
        "source":        item.source,
        "source_type":   item.source_type,
        "category":      item.category,
        "title":         item.title,
        "summary":       item.summary or "",
        "url":           item.url,
        "published_at":  item.published_at.isoformat() if item.published_at else None,
        "entity":        item.entity,
        "why_flagged":   item.flagged_reason or "",
    }


@router.post("/collect")
async def intel_collect(
    source: Optional[str] = Query(default=None, description="adapter name (생략 시 전체)"),
    limit: int = Query(default=50, ge=1, le=200),
):
    """
    Intel 수집 실행. 수 초 소요 가능 (FastAPI 동기 호출).
    Phase 2 에서 BackgroundTasks 로 분리 권장.
    """
    db = get_db()
    try:
        stats = await collect_all(db, source=source, limit_per_source=limit)
        return {"ok": True, **stats.as_dict()}
    finally:
        db.close()


@router.get("/shortlist")
async def intel_shortlist(
    category: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
):
    """
    shortlisted=True 카드 목록. category 필터 옵션.
    raw_payload 미포함.
    """
    # category 값 검증 — 잘못된 값이면 필터 없이 전체.
    cat_value: Optional[str] = None
    if category:
        try:
            cat_value = IntelCategory(category).value
        except ValueError:
            cat_value = None

    db = get_db()
    try:
        q = db.query(IntelItem).filter(IntelItem.shortlisted.is_(True))
        if cat_value:
            q = q.filter(IntelItem.category == cat_value)
        rows = (
            q.order_by(IntelItem.published_at.desc().nullslast(),
                       IntelItem.created_at.desc())
            .limit(limit)
            .all()
        )
        return {
            "items": [_card(r) for r in rows],
            "count": len(rows),
            "filter_category": cat_value,
        }
    finally:
        db.close()


@router.get("/items/{item_id}")
async def intel_item_detail(item_id: int, include_raw: bool = False):
    """
    단건 조회. include_raw=True 시에만 raw_payload 포함 (디버그용).
    """
    db = get_db()
    try:
        row = db.query(IntelItem).filter(IntelItem.id == item_id).first()
        if not row:
            raise HTTPException(status_code=404, detail="intel item not found")
        out = _card(row)
        out["shortlisted"] = row.shortlisted
        out["created_at"] = row.created_at.isoformat() if row.created_at else None
        if include_raw:
            out["raw_payload"] = row.raw_payload or ""
        return out
    finally:
        db.close()


@router.get("/status")
async def intel_status():
    """
    adapter enabled 여부 (key echo 금지), 총계, 최근 수집 시각.
    """
    db = get_db()
    try:
        counts = get_total_counts(db)
    finally:
        db.close()
    last = get_last_collect_at()
    return {
        "adapters":        settings.intel_sources_status(),  # True/False only
        "totals":          counts,
        "last_collect_at": last.isoformat() if last else None,
        "phase":           "1 (read-only, promote disabled)",
    }
