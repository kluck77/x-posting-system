"""
초안 서비스 테스트
==================
초안 생성, 상태 변경, 중복 방지를 테스트합니다.
"""

import pytest
from datetime import datetime, timezone
from app.models.content import (
    SourceItem, Draft, ContentCategory, RiskLevel, ApprovalStatus,
)
from app.services.draft_service import DraftService


@pytest.fixture
def source_item(db_session):
    """테스트용 소스 항목"""
    item = SourceItem(
        title="테스트 소스",
        url="https://example.com/test",
        source_text="테스트용 소스 텍스트입니다.",
        source_type="manual",
        language="ko",
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(item)
    db_session.commit()
    db_session.refresh(item)
    return item


class TestDraftService:
    def test_create_draft(self, db_session, source_item):
        service = DraftService(db_session)
        draft = service.create_draft(
            source_item=source_item,
            hook="Test hook",
            body="Test body text for X post",
            category=ContentCategory.SOCIETY,
            risk_level=RiskLevel.MEDIUM,
            risk_reasoning="Test risk reasoning",
        )
        assert draft.id is not None
        assert draft.hook == "Test hook"
        assert draft.body == "Test body text for X post"
        assert draft.category == ContentCategory.SOCIETY
        assert draft.risk_level == RiskLevel.MEDIUM
        assert draft.approval_status == ApprovalStatus.PENDING
        assert draft.version == 1

    def test_version_increments(self, db_session, source_item):
        service = DraftService(db_session)
        d1 = service.create_draft(
            source_item=source_item,
            hook="v1", body="v1 body",
            category=ContentCategory.SOCIETY,
            risk_level=RiskLevel.LOW,
        )
        d2 = service.create_draft(
            source_item=source_item,
            hook="v2", body="v2 body",
            category=ContentCategory.SOCIETY,
            risk_level=RiskLevel.LOW,
        )
        assert d1.version == 1
        assert d2.version == 2

    def test_update_status(self, db_session, source_item):
        service = DraftService(db_session)
        draft = service.create_draft(
            source_item=source_item,
            hook="hook", body="body",
            category=ContentCategory.EVERGREEN,
            risk_level=RiskLevel.LOW,
        )
        updated = service.update_status(draft.id, ApprovalStatus.APPROVED)
        assert updated.approval_status == ApprovalStatus.APPROVED

    def test_mark_published(self, db_session, source_item):
        service = DraftService(db_session)
        draft = service.create_draft(
            source_item=source_item,
            hook="hook", body="body",
            category=ContentCategory.EVERGREEN,
            risk_level=RiskLevel.LOW,
        )
        service.update_status(draft.id, ApprovalStatus.APPROVED)
        published = service.mark_published(draft.id, "12345", "https://x.com/i/status/12345")
        assert published.approval_status == ApprovalStatus.PUBLISHED
        assert published.x_post_id == "12345"
        assert published.published_at is not None

    def test_mark_failed(self, db_session, source_item):
        service = DraftService(db_session)
        draft = service.create_draft(
            source_item=source_item,
            hook="hook", body="body",
            category=ContentCategory.EVERGREEN,
            risk_level=RiskLevel.LOW,
        )
        failed = service.mark_failed(draft.id, "API error 429")
        assert failed.approval_status == ApprovalStatus.FAILED
        assert failed.error_message == "API error 429"
        assert failed.retry_count == 1

    def test_duplicate_detection(self, db_session, source_item):
        service = DraftService(db_session)
        service.create_draft(
            source_item=source_item,
            hook="hook", body="unique body text",
            category=ContentCategory.EVERGREEN,
            risk_level=RiskLevel.LOW,
        )
        assert service.is_duplicate_text("unique body text") is True
        assert service.is_duplicate_text("different body text") is False

    def test_get_pending(self, db_session, source_item):
        service = DraftService(db_session)
        service.create_draft(
            source_item=source_item,
            hook="h1", body="b1",
            category=ContentCategory.EVERGREEN,
            risk_level=RiskLevel.LOW,
        )
        service.create_draft(
            source_item=source_item,
            hook="h2", body="b2",
            category=ContentCategory.SOCIETY,
            risk_level=RiskLevel.MEDIUM,
        )
        pending = service.get_pending()
        assert len(pending) == 2

    def test_get_failed(self, db_session, source_item):
        service = DraftService(db_session)
        draft = service.create_draft(
            source_item=source_item,
            hook="hook", body="body",
            category=ContentCategory.EVERGREEN,
            risk_level=RiskLevel.LOW,
        )
        service.mark_failed(draft.id, "error")
        failed = service.get_failed()
        assert len(failed) == 1
