"""
Crypto Intel API (Phase 2 — 운영자 작업판)
==========================================
control_room 라우터가 이 모듈을 include 한다.
실제 경로는 /control/intel/* (control_room prefix='/control').

엔드포인트:
  POST /intel/collect                   — adapter 수집 트리거 (수 초 소요 가능)
  GET  /intel/shortlist                 — shortlisted=True 카드 목록
                                          정렬: score|recent|category
                                          상태 필터: all|unsent|sent
  GET  /intel/items/{id}                — 단건 상세 (raw_payload 기본 미노출)
  POST /intel/items/{id}/promote        — Orchestrator.full_pipeline 합류
                                          (중복 전송 방지: sent 면 409)
  GET  /intel/status                    — adapter enabled 여부 + 총계 + 최근 수집 시각
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import desc

from app.config import settings
from app.db import get_db
from app.models.content import SourceItemCreate
from app.models.intel import IntelItem
from app.orchestrator import Orchestrator
from app.services.intel.collect import (
    collect_all,
    get_last_collect_at,
    get_total_counts,
)
from app.services.intel.schema import IntelCategory
from app.services.intel.score import (
    classify_visibility_slot,
    compute_display_score,
    compute_freshness_penalty,
    is_cleanup_candidate,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/intel", tags=["crypto-intel"])

_HANGUL_RE = re.compile(r"[가-힣]")


def _age_hours(item: IntelItem, now: datetime) -> float:
    ref = item.published_at or item.created_at
    if not ref:
        return 0.0
    # DB 에서 오는 datetime 은 naive (utc) — 안전하게 tz 제거 비교
    try:
        ref_naive = ref.replace(tzinfo=None) if ref.tzinfo else ref
        now_naive = now.replace(tzinfo=None) if now.tzinfo else now
        delta = (now_naive - ref_naive).total_seconds()
        return max(0.0, delta / 3600.0)
    except Exception:
        return 0.0


def _card(item: IntelItem, now: Optional[datetime] = None) -> dict:
    """UI 카드 직렬화 — raw_payload / raw flagged_reason 미포함."""
    if now is None:
        now = datetime.now(timezone.utc)
    label = item.score_label or "noise"
    promo = item.promotion_status or "none"
    age_h = _age_hours(item, now)
    penalty = compute_freshness_penalty(age_h)
    disp = compute_display_score(int(item.priority_score or 0), penalty)
    slot = classify_visibility_slot(label, age_h, promo)
    cleanup = is_cleanup_candidate(label, age_h, promo)
    return {
        "id":                item.id,
        "source":            item.source,
        "source_type":       item.source_type,
        "category":          item.category,
        "title":             item.title,
        "summary":           item.summary or "",
        "url":               item.url,
        "published_at":      item.published_at.isoformat() if item.published_at else None,
        "entity":            item.entity,
        "priority_score":    int(item.priority_score or 0),
        "score_label":       label,
        "why_flagged_human": item.why_flagged_human or "",
        "promotion_status":  promo,
        "promoted_draft_id": item.promoted_draft_id,
        "promoted_at":       item.promoted_at.isoformat() if item.promoted_at else None,
        # Phase 6 — 시간 감쇠 / 슬롯 / cleanup
        "age_hours":             round(age_h, 2),
        "display_score":         disp,
        "visibility_slot":       slot,
        "is_cleanup_candidate":  cleanup,
    }


@router.post("/collect")
async def intel_collect(
    source: Optional[str] = Query(default=None, description="adapter name (생략 시 전체)"),
    limit: int = Query(default=50, ge=1, le=200),
):
    """Intel 수집 실행. 수 초 소요 가능 (FastAPI 동기 호출)."""
    db = get_db()
    try:
        stats = await collect_all(db, source=source, limit_per_source=limit)
        return {"ok": True, **stats.as_dict()}
    finally:
        db.close()


_MAIN_SLOT_LIMIT_CAP = 100  # Phase 6: main 슬롯 상한 (페이지네이션 지원)


@router.get("/shortlist")
async def intel_shortlist(
    category: Optional[str] = Query(default=None),
    sort: str = Query(default="score", description="score | recent | category"),
    status: str = Query(default="all", description="all | unsent | sent"),
    slot: str = Query(default="main", description="main | aged | secondary | cleanup | all"),
    limit: int = Query(default=50, ge=1, le=200),
):
    """
    Phase 6 — 슬롯 분리 + 시간 감쇠 정렬.
      slot=main        : 기본 노출 (strong/watch 24h, weak 12h)
      slot=aged        : 기본 window 초과한 strong/watch/weak 보조
      slot=secondary   : 6h 이내 noise
      slot=cleanup     : is_cleanup_candidate=True
      slot=all         : hidden 제외 전부 (디버그/운영자 전체보기)
    raw_payload / raw flagged_reason 미포함.
    """
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

        s = (status or "all").lower()
        if s == "sent":
            q = q.filter(IntelItem.promotion_status == "sent")
        elif s == "unsent":
            q = q.filter(IntelItem.promotion_status != "sent")

        # DB 단계에선 status/category 까지만 필터. slot 은 파생이므로 파이썬에서.
        # 정렬은 display_score 가 파생이라 파이썬에서 최종 적용.
        # created_at desc 로 당겨 놓고 (cap 보장) 파이썬에서 재정렬.
        rows = (
            q.order_by(desc(IntelItem.created_at)).limit(500).all()
        )
        now = datetime.now(timezone.utc)
        cards: list[dict[str, Any]] = [_card(r, now) for r in rows]

        # 슬롯 카운트 (hidden 포함 전체 집계 — UI 라벨용)
        slot_counts = {"main": 0, "aged": 0, "secondary": 0, "hidden": 0, "cleanup": 0}
        for c in cards:
            slot_counts[c["visibility_slot"]] = slot_counts.get(c["visibility_slot"], 0) + 1
            if c["is_cleanup_candidate"]:
                slot_counts["cleanup"] += 1

        # 슬롯 선택
        slot_key = (slot or "main").lower()
        if slot_key == "main":
            selected = [c for c in cards if c["visibility_slot"] == "main"]
        elif slot_key == "aged":
            selected = [c for c in cards if c["visibility_slot"] == "aged"]
        elif slot_key == "secondary":
            selected = [c for c in cards if c["visibility_slot"] == "secondary"]
        elif slot_key == "cleanup":
            selected = [c for c in cards if c["is_cleanup_candidate"]]
        else:  # "all" — hidden 제외
            selected = [c for c in cards if c["visibility_slot"] != "hidden"]

        # 정렬
        sort_key = (sort or "score").lower()
        if sort_key == "recent":
            selected.sort(
                key=lambda c: (c["published_at"] or "", c["id"]), reverse=True,
            )
        elif sort_key == "category":
            selected.sort(
                key=lambda c: (c["category"] or "", -c["display_score"]),
            )
        else:  # "score" (default) — display_score desc
            selected.sort(
                key=lambda c: (c["display_score"], c["published_at"] or "", c["id"]),
                reverse=True,
            )

        # limit — main 슬롯은 cap 적용 (운영자 "컨베이어벨트" 요구)
        effective_limit = min(limit, _MAIN_SLOT_LIMIT_CAP) if slot_key == "main" else limit
        selected = selected[:effective_limit]

        return {
            "items":           selected,
            "count":           len(selected),
            "filter_category": cat_value,
            "sort":            sort_key,
            "status":          s,
            "slot":            slot_key,
            "slot_counts":     slot_counts,
        }
    finally:
        db.close()


@router.get("/items/{item_id}")
async def intel_item_detail(item_id: int, include_raw: bool = False):
    """단건 조회. include_raw=True 시만 raw_payload/flagged_reason 포함."""
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
            out["flagged_reason"] = row.flagged_reason or ""
        return out
    finally:
        db.close()


def _detect_lang(text: str) -> str:
    """한글 유니코드 1 자 이상 → 'ko', 그 외 → 'en'."""
    return "ko" if _HANGUL_RE.search(text or "") else "en"


def _compose_source_text(row: IntelItem) -> str:
    """IntelItem → orchestrator 가 받을 source_text. AI 호출 0."""
    parts: list[str] = []
    if row.summary:
        parts.append(row.summary.strip())
    elif row.title:
        parts.append(row.title.strip())
    if row.entity:
        parts.append(f"엔티티: {row.entity.strip()}")
    if row.url:
        parts.append(f"출처: {row.url.strip()}")
    if row.why_flagged_human:
        parts.append(f"편집 신호: {row.why_flagged_human.strip()}")
    return "\n".join(parts)[:4000] or row.title or ""


@router.post("/items/{item_id}/promote")
async def intel_promote(item_id: int):
    """
    IntelItem 을 기존 Orchestrator.full_pipeline 에 합류시킨다.
    - 이미 sent 이고 promoted_draft_id 있음 → 409 Conflict + already=True
    - failed → 재시도 허용
    - 성공 시 promotion_status='sent', promoted_draft_id=N, promoted_at=now
    """
    db = get_db()
    try:
        row = db.query(IntelItem).filter(IntelItem.id == item_id).first()
        if not row:
            raise HTTPException(status_code=404, detail="intel item not found")

        if row.promotion_status == "sent" and row.promoted_draft_id:
            raise HTTPException(
                status_code=409,
                detail={
                    "already": True,
                    "draft_id": row.promoted_draft_id,
                    "promoted_at": row.promoted_at.isoformat() if row.promoted_at else None,
                },
            )

        title = (row.title or "").strip()
        lang = _detect_lang(f"{title} {row.summary or ''}")
        data = SourceItemCreate(
            title=title[:500] or "(untitled)",
            url=row.url,
            source_text=_compose_source_text(row) or title or "(no content)",
            source_type=f"intel:{row.source}",
            language=lang,
        )

        orch = Orchestrator(db)
        try:
            result = await orch.full_pipeline(data)
        except Exception as e:
            logger.error("[intel promote] orchestrator exception: %s", e, exc_info=True)
            result = {"success": False, "error": str(e)}
        finally:
            try:
                orch.close()
            except Exception:
                pass

        if result.get("success"):
            row.promoted_draft_id = result.get("draft_id")
            row.promotion_status = "sent"
            row.promoted_at = datetime.now(timezone.utc)
            db.commit()
            return {
                "ok": True,
                "draft_id": row.promoted_draft_id,
                "telegram_sent": bool(result.get("telegram_sent")),
                "promotion_status": "sent",
                "promoted_at": row.promoted_at.isoformat(),
            }
        else:
            row.promotion_status = "failed"
            db.commit()
            return {
                "ok": False,
                "error": result.get("error") or "unknown",
                "promotion_status": "failed",
            }
    finally:
        db.close()


@router.get("/status")
async def intel_status():
    """adapter enabled 여부 (key echo 금지), 총계, 최근 수집 시각."""
    db = get_db()
    try:
        counts = get_total_counts(db)
    finally:
        db.close()
    last = get_last_collect_at()
    return {
        "adapters":        settings.intel_sources_status(),
        "totals":          counts,
        "last_collect_at": last.isoformat() if last else None,
        "phase":           "2 (scoring + promote)",
    }
