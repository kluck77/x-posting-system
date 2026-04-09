"""
FastAPI 관리자/디버그 엔드포인트
=================================
헬스체크, 초안 목록, 수동 파이프라인 실행 등을 제공합니다.
브라우저에서 http://localhost:8000/docs 로 접속하면 API 문서를 볼 수 있습니다.
"""

import logging
from fastapi import FastAPI, HTTPException
from sqlalchemy import text
from app.config import settings, validate_settings
from app.db import get_db, init_db
from app.models.content import (
    SourceItemCreate, DraftResponse, HealthResponse, ApprovalStatus,
)
from app.services.draft_service import DraftService
from app.services.source_service import SourceService
from app.orchestrator import Orchestrator

logger = logging.getLogger(__name__)

# FastAPI 앱 생성
app = FastAPI(
    title="X Posting System - Admin API",
    description="한국 이슈 영문 X 포스팅 시스템 관리 API",
    version="1.0.0",
)


@app.on_event("startup")
async def startup():
    """앱 시작 시 DB 초기화 및 설정 검증"""
    init_db()
    warnings = validate_settings(settings)
    for w in warnings:
        logger.warning(w)
    ai_status = settings.ai_status_summary()
    logger.info(f"AI 상태: {ai_status}")


# === 헬스체크 ===

@app.get("/health", response_model=HealthResponse)
async def health_check():
    """시스템 상태를 확인합니다."""
    db_ok = False
    try:
        db = get_db()
        db.execute(text("SELECT 1"))
        db_ok = True
        db.close()
    except Exception:
        pass

    return HealthResponse(
        status="ok",
        mock_mode=settings.is_full_mock_mode,
        telegram_configured=settings.has_telegram_config,
        x_configured=settings.has_x_credentials,
        database_ok=db_ok,
    )


@app.get("/status")
async def system_status():
    """AI 프로바이더별 상태를 보여줍니다."""
    return {
        "ai_providers": settings.ai_status_summary(),
        "settings": {
            "auto_post_enabled": settings.enable_auto_post_low_risk,
            "language": settings.default_language,
            "log_level": settings.log_level,
        },
    }


# === 소스 관리 ===

@app.post("/ingest")
async def ingest_source(data: SourceItemCreate):
    """
    소스를 입력하고 전체 AI 파이프라인을 실행합니다.
    완료되면 텔레그램에 승인 카드가 전송됩니다.
    """
    orchestrator = Orchestrator()
    try:
        result = await orchestrator.full_pipeline(data)
        return result
    finally:
        orchestrator.close()


# === 초안 관리 ===

@app.get("/drafts/pending")
async def get_pending_drafts():
    """검토 대기 중인 초안 목록"""
    db = get_db()
    try:
        service = DraftService(db)
        drafts = service.get_pending()
        return [
            {
                "id": d.id,
                "hook": d.hook,
                "body": d.body[:100] + "..." if len(d.body) > 100 else d.body,
                "category": d.category.value,
                "risk_level": d.risk_level.value,
                "created_at": d.created_at.isoformat() if d.created_at else None,
            }
            for d in drafts
        ]
    finally:
        db.close()


@app.get("/drafts/approved")
async def get_approved_drafts():
    """승인된 초안 목록"""
    db = get_db()
    try:
        service = DraftService(db)
        drafts = service.get_approved()
        return [
            {
                "id": d.id,
                "hook": d.hook,
                "category": d.category.value,
                "risk_level": d.risk_level.value,
            }
            for d in drafts
        ]
    finally:
        db.close()


@app.get("/drafts/failed")
async def get_failed_drafts():
    """게시 실패한 초안 목록"""
    db = get_db()
    try:
        service = DraftService(db)
        drafts = service.get_failed()
        return [
            {
                "id": d.id,
                "hook": d.hook,
                "error_message": d.error_message,
                "retry_count": d.retry_count,
            }
            for d in drafts
        ]
    finally:
        db.close()


@app.get("/drafts/{draft_id}")
async def get_draft_detail(draft_id: int):
    """초안 상세 정보"""
    db = get_db()
    try:
        service = DraftService(db)
        draft = service.get_by_id(draft_id)
        if not draft:
            raise HTTPException(status_code=404, detail="초안을 찾을 수 없습니다")
        return {
            "id": draft.id,
            "hook": draft.hook,
            "body": draft.body,
            "thread_continuation": draft.thread_continuation,
            "category": draft.category.value,
            "risk_level": draft.risk_level.value,
            "risk_reasoning": draft.risk_reasoning,
            "ai_rationale": draft.ai_rationale,
            "approval_status": draft.approval_status.value,
            "x_post_id": draft.x_post_id,
            "x_post_url": draft.x_post_url,
            "version": draft.version,
            "created_at": draft.created_at.isoformat() if draft.created_at else None,
            "published_at": draft.published_at.isoformat() if draft.published_at else None,
        }
    finally:
        db.close()


# === 수동 승인/거절 ===

@app.post("/drafts/{draft_id}/approve")
async def approve_draft(draft_id: int):
    """초안을 수동으로 승인하고 X에 게시합니다."""
    orchestrator = Orchestrator()
    try:
        result = await orchestrator.handle_approval(draft_id, "approve")
        return result
    finally:
        orchestrator.close()


@app.post("/drafts/{draft_id}/reject")
async def reject_draft(draft_id: int):
    """초안을 수동으로 거절합니다."""
    orchestrator = Orchestrator()
    try:
        result = await orchestrator.handle_approval(draft_id, "reject")
        return result
    finally:
        orchestrator.close()


@app.post("/drafts/{draft_id}/retry")
async def retry_draft(draft_id: int):
    """실패한 게시를 재시도합니다."""
    orchestrator = Orchestrator()
    try:
        result = await orchestrator.retry_failed(draft_id)
        return result
    finally:
        orchestrator.close()


# === 일일 사용량 ===

@app.get("/usage")
async def daily_usage():
    """오늘의 일일 사용량과 남은 한도를 확인합니다."""
    from app.services.rate_limiter import RateLimiter
    db = get_db()
    try:
        limiter = RateLimiter(db)
        return limiter.get_daily_summary()
    finally:
        db.close()
