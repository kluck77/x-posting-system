# app/orchestrator.py
"""
오케스트레이터 (5-역할 AI 파이프라인)
초안 저장 후 prediction_service 호출 위치: create_draft() 호출 직후 (약 161번 줄)
"""

import logging
from sqlalchemy.orm import Session
from app.config import settings
from app.db import get_db
from app.models.content import (
    SourceItem, Draft, ContentCategory, RiskLevel, ApprovalStatus,
    SourceItemCreate,
)
from app.services.source_service import SourceService
from app.services.draft_service import DraftService
from app.services.classifier import classify_category, classify_risk
from app.services.telegram_service import send_approval_card, send_publish_confirmation
from app.services.x_publisher import XPublisher
from app.services.rate_limiter import RateLimiter
from app.providers.ai_provider import AITeam, create_ai_team
from app.providers.base import DraftResult, ResearchResult

logger = logging.getLogger(__name__)


class Orchestrator:
    def __init__(self, db: Session | None = None):
        self.db = db or get_db()
        self.source_service = SourceService(self.db)
        self.draft_service = DraftService(self.db)
        self.x_publisher = XPublisher(self.db)
        self.rate_limiter = RateLimiter(self.db)
        self.ai: AITeam = create_ai_team()

    async def ingest_and_generate(self, data: SourceItemCreate) -> Draft:
        logger.info(f"=== 파이프라인 시작: '{data.title[:50]}' ===")

        can_draft, draft_msg = self.rate_limiter.can_create_draft()
        if not can_draft:
            raise RuntimeError(f"일일 제한 초과: {draft_msg}")

        source_item = self.source_service.ingest_manual(data)

        try:
            research = await self.ai.researcher.research(
                query=data.title, context=data.source_text[:1000],
            )
        except Exception as e:
            research = ResearchResult(
                summary=data.source_text[:500],
                sources=[data.url] if data.url else [],
            )

        try:
            draft_result = await self.ai.draft_writer.generate_draft(
                title=data.title,
                source_text=data.source_text,
                language=settings.default_language,
            )
        except Exception as e:
            draft_result = DraftResult(
                hook=f"\U0001f1f0\U0001f1f7 {data.title[:80]}",
                body=f"Korea update: {data.title[:200]}",
                category_suggestion="society",
            )

        try:
            factcheck = await self.ai.fact_checker.check_facts(
                claim=draft_result.body, context=data.source_text[:500],
            )
        except Exception as e:
            factcheck = None

        try:
            review = await self.ai.reviewer.review_and_refine(
                title=data.title,
                source_text=data.source_text,
                draft=draft_result,
                research=research,
                factcheck=factcheck,
            )
        except Exception as e:
            from app.providers.base import ReviewResult
            review = ReviewResult(
                hook=draft_result.hook,
                body=draft_result.body,
                thread_continuation=draft_result.thread_continuation,
                category=draft_result.category_suggestion,
                risk_level="medium",
                risk_reasoning=f"Reviewer 실패: {e}",
                ai_rationale="Fallback: reviewer unavailable.",
            )

        try:
            category = ContentCategory(review.category)
        except ValueError:
            category = classify_category(data.title, data.source_text)

        try:
            risk_level = RiskLevel(review.risk_level)
            risk_reasoning = review.risk_reasoning
        except ValueError:
            risk_level, risk_reasoning = classify_risk(
                data.title, data.source_text, category,
            )

        if self.draft_service.is_duplicate_text(review.body):
            logger.warning("중복 텍스트 감지!")

        # 초안 저장 (161번 줄)
        draft = self.draft_service.create_draft(
            source_item=source_item,
            hook=review.hook,
            body=review.body,
            category=category,
            risk_level=risk_level,
            risk_reasoning=risk_reasoning,
            ai_rationale=review.ai_rationale,
            thread_continuation=review.thread_continuation,
        )

        # [TODO] 여기에 prediction_service 호출 추가:
        # from app.services.prediction_service import predict_publish_time
        # from datetime import datetime, timezone
        # pred_time, pred_reason = predict_publish_time(draft.category, draft.risk_level, datetime.now(timezone.utc))
        # draft.predicted_publish_at = pred_time
        # draft.prediction_reasoning = pred_reason
        # self.db.commit()

        return draft

    async def send_for_approval(self, draft_id: int) -> bool:
        can_send, send_msg = self.rate_limiter.can_send_telegram()
        if not can_send:
            return False
        draft = self.draft_service.get_by_id(draft_id)
        if not draft:
            return False
        source_url = draft.source_item.url if draft.source_item else None
        message_id = await send_approval_card(draft, source_url)
        if message_id:
            self.draft_service.set_telegram_message_id(draft_id, message_id)
            return True
        elif not settings.has_telegram_config:
            return True
        else:
            return False

    async def handle_approval(self, draft_id: int, action: str) -> dict:
        draft = self.draft_service.get_by_id(draft_id)
        if not draft:
            return {"success": False, "error": f"초안 없음: {draft_id}"}
        if action == "approve":
            return await self._handle_approve(draft)
        elif action == "reject":
            self.draft_service.update_status(draft_id, ApprovalStatus.REJECTED)
            return {"success": True, "message": "거절됨"}
        elif action == "defer":
            self.draft_service.update_status(draft_id, ApprovalStatus.DEFERRED)
            return {"success": True, "message": "보류됨"}
        elif action == "regenerate":
            self.draft_service.update_status(draft_id, ApprovalStatus.REGENERATE)
            return await self._handle_regenerate(draft)
        else:
            return {"success": False, "error": f"알 수 없는 액션: {action}"}

    async def _handle_approve(self, draft: Draft) -> dict:
        can_post, post_msg = self.rate_limiter.can_publish()
        if not can_post:
            return {"success": False, "error": f"일일 게시 한도 초과: {post_msg}"}
        self.draft_service.update_status(draft.id, ApprovalStatus.APPROVED)
        result = await self.x_publisher.publish(draft)
        if result.success:
            self.draft_service.mark_published(draft.id, result.post_id, result.post_url)
            updated = self.draft_service.get_by_id(draft.id)
            await send_publish_confirmation(updated)
            return {"success": True, "x_post_id": result.post_id, "x_post_url": result.post_url}
        else:
            self.draft_service.mark_failed(draft.id, result.error_message or "Unknown")
            return {"success": False, "error": f"X 게시 실패: {result.error_message}"}

    async def _handle_regenerate(self, draft: Draft) -> dict:
        source = draft.source_item
        if not source:
            return {"success": False, "error": "원본 소스 없음"}
        try:
            new_data = SourceItemCreate(
                title=source.title, url=source.url,
                source_text=source.source_text,
                source_type=source.source_type, language=source.language,
            )
            new_draft = await self.ingest_and_generate(new_data)
            await self.send_for_approval(new_draft.id)
            return {"success": True, "new_draft_id": new_draft.id}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def full_pipeline(self, data: SourceItemCreate) -> dict:
        try:
            draft = await self.ingest_and_generate(data)
            sent = await self.send_for_approval(draft.id)
            return {
                "success": True,
                "draft_id": draft.id,
                "category": draft.category.value,
                "risk_level": draft.risk_level.value,
                "telegram_sent": sent,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def close(self):
        if self.db:
            self.db.close()
