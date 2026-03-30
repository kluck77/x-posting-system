"""
X 퍼블리셔 테스트
==================
게시 서비스의 안전 체크 로직을 테스트합니다.
"""

import pytest
from datetime import datetime, timezone
from app.models.content import (
    SourceItem, Draft, ContentCategory, RiskLevel, ApprovalStatus,
)
from app.services.x_publisher import XPublisher


@pytest.fixture
def source_item(db_session):
    item = SourceItem(
        title="Test", url="https://example.com",
        source_text="Test text", source_type="manual",
        language="ko", created_at=datetime.now(timezone.utc),
    )
    db_session.add(item)
    db_session.commit()
    db_session.refresh(item)
    return item


@pytest.fixture
def approved_draft(db_session, source_item):
    draft = Draft(
        source_item_id=source_item.id,
        hook="Test hook",
        body="Test body",
        category=ContentCategory.EVERGREEN,
        risk_level=RiskLevel.LOW,
        approval_status=ApprovalStatus.APPROVED,
        version=1,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db_session.add(draft)
    db_session.commit()
    db_session.refresh(draft)
    return draft


class TestXPublisher:
    @pytest.mark.asyncio
    async def test_mock_publish_success(self, db_session, approved_draft):
        """Mock 모드에서 게시 성공 테스트"""
        publisher = XPublisher(db_session)
        result = await publisher.publish(approved_draft)
        assert result.success is True
        assert result.post_id is not None
        assert "mock_" in result.post_id

    @pytest.mark.asyncio
    async def test_reject_unapproved(self, db_session, source_item):
        """승인되지 않은 초안 게시 거부 테스트"""
        draft = Draft(
            source_item_id=source_item.id,
            hook="hook", body="body",
            category=ContentCategory.POLITICS,
            risk_level=RiskLevel.HIGH,
            approval_status=ApprovalStatus.PENDING,
            version=1,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db_session.add(draft)
        db_session.commit()
        db_session.refresh(draft)

        publisher = XPublisher(db_session)
        result = await publisher.publish(draft)
        assert result.success is False
        assert "승인되지 않은" in result.error_message

    @pytest.mark.asyncio
    async def test_reject_already_published(self, db_session, approved_draft):
        """이미 게시된 초안 중복 게시 방지 테스트"""
        approved_draft.x_post_id = "existing_123"
        db_session.commit()

        publisher = XPublisher(db_session)
        result = await publisher.publish(approved_draft)
        assert result.success is False
        assert "이미 게시된" in result.error_message
