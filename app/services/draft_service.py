"""
초안 관리 서비스
================
AI가 생성한 포스트 초안을 데이터베이스에 저장하고 관리합니다.
중복 방지, 버전 관리, 상태 업데이트 등을 처리합니다.
"""

import logging
from datetime import datetime, timezone
from sqlalchemy.orm import Session
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

    def is_duplicate_text(self, text: str) -> bool:
        """
        동일한 텍스트가 이미 게시되었거나 승인 대기 중인지 확인합니다.
        중복 게시를 방지합니다.
        """
        existing = (
            self.db.query(Draft)
            .filter(
                Draft.body == text.strip(),
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

    def save_performance_note(self, draft_id: int, note: str) -> Draft | None:
        """
        게시 후 성과 메모를 manual_notes에 [PERF] 태그로 추가합니다.

        pre-draft 메모(/note)와 구분하기 위해 [PERF] 접두어를 사용합니다.
        기존 메모가 있으면 줄바꿈 후 추가합니다.
        """
        draft = self.get_by_id(draft_id)
        if not draft:
            return None
        tag = f"[PERF] {note.strip()}"
        if draft.manual_notes:
            draft.manual_notes = draft.manual_notes + f"\n{tag}"
        else:
            draft.manual_notes = tag
        self.db.commit()
        self.db.refresh(draft)
        logger.info(f"성과 메모 저장: draft_id={draft_id}, note={note[:60]}")
        return draft

    def get_published_with_perf_notes(self, limit: int = 5) -> list[Draft]:
        """
        [PERF] 태그가 있는 최근 게시 초안을 반환합니다.

        성과 패턴 파악 및 프롬프트 개선 참고용.
        """
        return (
            self.db.query(Draft)
            .filter(
                Draft.approval_status == ApprovalStatus.PUBLISHED,
                Draft.manual_notes.like("%[PERF]%"),
            )
            .order_by(Draft.published_at.desc())
            .limit(limit)
            .all()
        )
