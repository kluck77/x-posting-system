"""
초안 관리 서비스
================
AI가 생성한 포스트 초안을 데이터베이스에 저장하고 관리합니다.
중복 방지, 버전 관리, 상태 업데이트 등을 처리합니다.
"""

import logging
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import and_
from app.models.content import (
    Draft, SourceItem, ApprovalStatus, ContentCategory, RiskLevel
)

logger = logging.getLogger(__name__)


class DraftService:
    """초안 관리 서비스"""

    def __init__(self, db: Session):
        self.db = db

    def create_draft(
        self,
        source_item: SourceItem,
        hook: str,
        body: str,
        category: ContentCategory,
        risk_level: RiskLevel,
        risk_reasoning: str = "",
        ai_rationale: str = "",
        thread_continuation: str | None = None,
    ) -> Draft:
        """
        새 초안을 생성합니다.

        Args:
            source_item: 원본 소스 항목
            hook: 훅/제목 텍스트
            body: 본문 텍스트
            category: 콘텐츠 카테고리
            risk_level: 위험 수준
            risk_reasoning: 위험도 판단 근거
            ai_rationale: AI 추천 이유
            thread_continuation: 스레드 연속 텍스트 (선택)

        Returns:
            생성된 Draft 객체
        """
        # 이 소스에서 생성된 최신 버전 확인
        latest = (
            self.db.query(Draft)
            .filter(Draft.source_item_id == source_item.id)
            .order_by(Draft.version.desc())
            .first()
        )
        new_version = (latest.version + 1) if latest else 1

        draft = Draft(
            source_item_id=source_item.id,
            hook=hook.strip(),
            body=body.strip(),
            thread_continuation=thread_continuation.strip() if thread_continuation else None,
            category=category,
            risk_level=risk_level,
            risk_reasoning=risk_reasoning,
            ai_rationale=ai_rationale,
            approval_status=ApprovalStatus.PENDING,
            version=new_version,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        self.db.add(draft)
        self.db.commit()
        self.db.refresh(draft)

        logger.info(
            f"초안 생성 완료: draft_id={draft.id}, "
            f"source_id={source_item.id}, version={new_version}"
        )
        return draft

    def get_by_id(self, draft_id: int) -> Draft | None:
        """ID로 초안을 조회합니다."""
        return self.db.query(Draft).filter(Draft.id == draft_id).first()

    def get_pending(self) -> list[Draft]:
        """검토 대기 중인 초안 목록을 조회합니다."""
        return (
            self.db.query(Draft)
            .filter(Draft.approval_status == ApprovalStatus.PENDING)
            .order_by(Draft.created_at.asc())
            .all()
        )

    def get_approved(self) -> list[Draft]:
        """승인된 초안 목록을 조회합니다 (아직 게시되지 않은 것)."""
        return (
            self.db.query(Draft)
            .filter(Draft.approval_status == ApprovalStatus.APPROVED)
            .order_by(Draft.created_at.asc())
            .all()
        )

    def get_failed(self) -> list[Draft]:
        """게시 실패한 초안 목록을 조회합니다."""
        return (
            self.db.query(Draft)
            .filter(Draft.approval_status == ApprovalStatus.FAILED)
            .order_by(Draft.created_at.desc())
            .all()
        )

    def update_status(self, draft_id: int, status: ApprovalStatus) -> Draft | None:
        """초안의 승인 상태를 변경합니다."""
        draft = self.get_by_id(draft_id)
        if not draft:
            logger.warning(f"초안을 찾을 수 없음: draft_id={draft_id}")
            return None

        old_status = draft.approval_status
        draft.approval_status = status
        draft.updated_at = datetime.now(timezone.utc)
        self.db.commit()
        self.db.refresh(draft)

        logger.info(f"초안 상태 변경: draft_id={draft_id}, {old_status} -> {status}")
        return draft

    def mark_published(self, draft_id: int, x_post_id: str, x_post_url: str) -> Draft | None:
        """초안을 게시 완료로 표시합니다."""
        draft = self.get_by_id(draft_id)
        if not draft:
            return None

        draft.approval_status = ApprovalStatus.PUBLISHED
        draft.x_post_id = x_post_id
        draft.x_post_url = x_post_url
        draft.published_at = datetime.now(timezone.utc)
        draft.updated_at = datetime.now(timezone.utc)
        self.db.commit()
        self.db.refresh(draft)

        logger.info(f"게시 완료: draft_id={draft_id}, x_post_id={x_post_id}")
        return draft

    def mark_failed(self, draft_id: int, error_message: str) -> Draft | None:
        """초안을 게시 실패로 표시합니다."""
        draft = self.get_by_id(draft_id)
        if not draft:
            return None

        draft.approval_status = ApprovalStatus.FAILED
        draft.error_message = error_message
        draft.retry_count += 1
        draft.updated_at = datetime.now(timezone.utc)
        self.db.commit()
        self.db.refresh(draft)

        logger.warning(f"게시 실패: draft_id={draft_id}, error={error_message[:100]}")
        return draft

    def set_telegram_message_id(self, draft_id: int, telegram_message_id: int) -> None:
        """텔레그램 메시지 ID를 저장합니다."""
        draft = self.get_by_id(draft_id)
        if draft:
            draft.telegram_message_id = telegram_message_id
            self.db.commit()

    def get_recent_operator_hints(self, limit: int = 3) -> list[str]:
        """최근 Draft의 manual_notes에서 operator hints를 가져옵니다."""
        drafts = (
            self.db.query(Draft)
            .filter(
                and_(
                    Draft.manual_notes.isnot(None),
                    Draft.manual_notes != "",
                )
            )
            .order_by(Draft.created_at.desc())
            .limit(limit)
            .all()
        )
        return [d.manual_notes.strip() for d in drafts if d.manual_notes and d.manual_notes.strip()]

    def cleanup_stale_drafts(
        self,
        pending_days: int = 7,
        rejected_days: int = 30,
        failed_days: int = 30,
    ) -> dict[str, int]:
        """
        오래된 Draft를 자동 삭제합니다.

        정책:
        - PENDING: pending_days일 경과 시 삭제
        - REJECTED: rejected_days일 경과 시 삭제
        - FAILED: failed_days일 경과 시 삭제
        - APPROVED / PUBLISHED: 삭제하지 않음

        Returns:
            {"pending": 삭제 수, "rejected": 삭제 수, "failed": 삭제 수}
        """
        now = datetime.now(timezone.utc)
        counts: dict[str, int] = {}

        for status, days, label in [
            (ApprovalStatus.PENDING, pending_days, "pending"),
            (ApprovalStatus.REJECTED, rejected_days, "rejected"),
            (ApprovalStatus.FAILED, failed_days, "failed"),
        ]:
            cutoff = now - timedelta(days=days)
            deleted = (
                self.db.query(Draft)
                .filter(
                    Draft.approval_status == status,
                    Draft.created_at < cutoff,
                )
                .delete(synchronize_session="fetch")
            )
            counts[label] = deleted

        self.db.commit()
        total = sum(counts.values())
        if total > 0:
            logger.info(
                f"[draft-cleanup] 정리 완료: {counts} (합계 {total}건 삭제)"
            )
        return counts

    def is_duplicate_text(self, text: str) -> bool:
        """
        동일한 텍스트가 이미 게시되었거나 승인 대기 중인지 확인합니다.
        중복 게시를 방지합니다.
        """
        existing = (
            self.db.query(Draft)
            .filter(
                Draft.body == (text or "").strip(),
                Draft.approval_status.in_([
                    ApprovalStatus.PENDING,
                    ApprovalStatus.APPROVED,
                    ApprovalStatus.PUBLISHED,
                ])
            )
            .first()
        )
        if existing:
            logger.warning(f"중복 텍스트 감지: 기존 draft_id={existing.id}")
            return True
        return False
