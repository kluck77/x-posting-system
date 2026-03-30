"""
일일 사용량 제한 테스트
========================
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timezone, timedelta
from app.models.content import (
    SourceItem, Draft, ContentCategory, RiskLevel, ApprovalStatus,
)
from app.services.rate_limiter import RateLimiter


def _create_source(db_session) -> SourceItem:
    """테스트용 소스 생성"""
    source = SourceItem(
        title="테스트 소스",
        source_text="테스트 텍스트",
        source_type="manual",
        language="ko",
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(source)
    db_session.commit()
    db_session.refresh(source)
    return source


def _create_draft(db_session, source_id: int, **kwargs) -> Draft:
    """테스트용 초안 생성"""
    defaults = {
        "source_item_id": source_id,
        "hook": "Test hook",
        "body": "Test body",
        "category": ContentCategory.EVERGREEN,
        "risk_level": RiskLevel.LOW,
        "approval_status": ApprovalStatus.PENDING,
        "version": 1,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }
    defaults.update(kwargs)
    draft = Draft(**defaults)
    db_session.add(draft)
    db_session.commit()
    db_session.refresh(draft)
    return draft


class TestRateLimiter:
    """RateLimiter 테스트"""

    def test_can_create_draft_within_limit(self, db_session):
        """제한 내에서 초안 생성 가능"""
        limiter = RateLimiter(db_session, max_drafts=5)
        allowed, msg = limiter.can_create_draft()
        assert allowed is True

    def test_cannot_create_draft_over_limit(self, db_session):
        """제한 초과 시 초안 생성 불가"""
        source = _create_source(db_session)
        limiter = RateLimiter(db_session, max_drafts=2)

        _create_draft(db_session, source.id)
        _create_draft(db_session, source.id, body="body 2")

        allowed, msg = limiter.can_create_draft()
        assert allowed is False
        assert "한도 초과" in msg

    def test_can_publish_within_limit(self, db_session):
        """제한 내에서 게시 가능"""
        limiter = RateLimiter(db_session, max_posts=3)
        allowed, msg = limiter.can_publish()
        assert allowed is True

    def test_cannot_publish_over_limit(self, db_session):
        """제한 초과 시 게시 불가"""
        source = _create_source(db_session)
        limiter = RateLimiter(db_session, max_posts=1)

        _create_draft(
            db_session, source.id,
            approval_status=ApprovalStatus.PUBLISHED,
            published_at=datetime.now(timezone.utc),
        )

        allowed, msg = limiter.can_publish()
        assert allowed is False

    def test_can_send_telegram_within_limit(self, db_session):
        """제한 내에서 텔레그램 전송 가능"""
        limiter = RateLimiter(db_session, max_telegram=5)
        allowed, msg = limiter.can_send_telegram()
        assert allowed is True

    def test_cannot_send_telegram_over_limit(self, db_session):
        """제한 초과 시 텔레그램 전송 불가"""
        source = _create_source(db_session)
        limiter = RateLimiter(db_session, max_telegram=1)

        _create_draft(db_session, source.id, telegram_message_id=12345)

        allowed, msg = limiter.can_send_telegram()
        assert allowed is False

    def test_daily_summary(self, db_session):
        """일일 요약 반환"""
        limiter = RateLimiter(db_session, max_drafts=5, max_telegram=5, max_posts=3)
        summary = limiter.get_daily_summary()

        assert summary["drafts"]["used"] == 0
        assert summary["drafts"]["limit"] == 5
        assert summary["posts"]["used"] == 0
        assert summary["posts"]["limit"] == 3
        assert summary["telegram"]["used"] == 0
        assert summary["telegram"]["limit"] == 5

    def test_old_drafts_not_counted(self, db_session):
        """어제 생성된 초안은 오늘 카운트에 포함되지 않음"""
        source = _create_source(db_session)
        limiter = RateLimiter(db_session, max_drafts=1)

        # 어제 만든 초안
        yesterday = datetime.now(timezone.utc) - timedelta(days=1)
        _create_draft(db_session, source.id, created_at=yesterday)

        allowed, msg = limiter.can_create_draft()
        assert allowed is True


class TestSourceDuplicateURL:
    """URL 중복 방지 테스트"""

    def test_duplicate_url_detected(self, db_session):
        """동일 URL 감지"""
        from app.services.source_service import SourceService
        service = SourceService(db_session)

        source = SourceItem(
            title="기존 소스", url="https://example.com/article1",
            source_text="text", source_type="manual", language="ko",
            created_at=datetime.now(timezone.utc),
        )
        db_session.add(source)
        db_session.commit()

        assert service.is_duplicate_url("https://example.com/article1") is True

    def test_new_url_not_duplicate(self, db_session):
        """새로운 URL은 중복 아님"""
        from app.services.source_service import SourceService
        service = SourceService(db_session)
        assert service.is_duplicate_url("https://example.com/new") is False

    def test_empty_url_not_duplicate(self, db_session):
        """빈 URL은 중복 체크 스킵"""
        from app.services.source_service import SourceService
        service = SourceService(db_session)
        assert service.is_duplicate_url("") is False
        assert service.is_duplicate_url(None) is False
