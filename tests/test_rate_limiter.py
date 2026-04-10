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


class TestLaneBasedRateLimiting:
    """레인별 AI 파이프라인 제한 테스트"""

    def _create_source(self, db_session, source_type="manual"):
        source = SourceItem(
            title="테스트 소스",
            source_text="테스트 텍스트",
            source_type=source_type,
            language="ko",
            created_at=datetime.now(timezone.utc),
        )
        db_session.add(source)
        db_session.commit()
        db_session.refresh(source)
        return source

    def _create_ai_draft(self, db_session, source_id, body="AI generated content"):
        """AI 파이프라인을 거친 일반 드래프트"""
        return _create_draft(db_session, source_id, body=body)

    def _create_ko_only_draft(self, db_session, source_id):
        """KO-only 드래프트 (Step 1.7 early return)"""
        return _create_draft(
            db_session, source_id,
            hook="[CANDIDATE] 테스트 기사",
            body="한국어 전용 라인 처리 (영어 초안 생략). domain=금융",
        )

    def test_ai_draft_count_excludes_ko_only(self, db_session):
        """AI 카운트에서 KO-only 드래프트 제외"""
        source = self._create_source(db_session)
        self._create_ai_draft(db_session, source.id, body="AI draft 1")
        self._create_ai_draft(db_session, source.id, body="AI draft 2")
        self._create_ko_only_draft(db_session, source.id)

        limiter = RateLimiter(db_session, max_ai_drafts=20)
        assert limiter.get_today_ai_draft_count() == 2  # KO-only 제외

    def test_ai_draft_count_by_source_type(self, db_session):
        """source_type 별 AI 카운트 분리"""
        manual_src = self._create_source(db_session, source_type="manual")
        auto_src = self._create_source(db_session, source_type="naver_auto")

        self._create_ai_draft(db_session, manual_src.id, body="Manual AI draft")
        self._create_ai_draft(db_session, auto_src.id, body="Auto AI draft 1")
        self._create_ai_draft(db_session, auto_src.id, body="Auto AI draft 2")

        limiter = RateLimiter(db_session, max_ai_drafts=20)
        assert limiter.get_today_ai_draft_count() == 3
        assert limiter.get_today_ai_draft_count(source_type="manual") == 1
        assert limiter.get_today_auto_ai_draft_count() == 2

    def test_breaking_and_ko_only_bypass_rate_check(self, db_session):
        """BREAKING/KO-only 드래프트는 AI 카운트에 영향 없음"""
        source = self._create_source(db_session, source_type="naver_auto")
        # KO-only 50건 생성 — 이것만으로 AI 한도 미소진
        for _ in range(50):
            self._create_ko_only_draft(db_session, source.id)

        limiter = RateLimiter(db_session, max_ai_drafts=20)
        assert limiter.get_today_ai_draft_count() == 0
        can, _ = limiter.can_run_ai_pipeline(source_type="naver_auto")
        assert can is True

    def test_auto_limited_by_reserved_slots(self, db_session):
        """자동수집은 max_ai - manual_reserved 까지만"""
        auto_src = self._create_source(db_session, source_type="naver_auto")

        limiter = RateLimiter(
            db_session, max_ai_drafts=10, manual_reserved=3,
        )
        # auto limit = 10 - 3 = 7
        for i in range(7):
            self._create_ai_draft(
                db_session, auto_src.id, body=f"Auto AI draft {i}",
            )

        can, msg = limiter.can_run_ai_pipeline(source_type="naver_auto")
        assert can is False
        assert "자동수집" in msg
        assert "3슬롯 예약" in msg

    def test_manual_uses_full_limit(self, db_session):
        """수동 입력은 전체 한도 사용 가능"""
        auto_src = self._create_source(db_session, source_type="naver_auto")
        manual_src = self._create_source(db_session, source_type="manual")

        limiter = RateLimiter(
            db_session, max_ai_drafts=10, manual_reserved=3,
        )
        # auto 7건 → auto 한도 소진
        for i in range(7):
            self._create_ai_draft(
                db_session, auto_src.id, body=f"Auto AI draft {i}",
            )

        # auto 차단
        can_auto, _ = limiter.can_run_ai_pipeline(source_type="naver_auto")
        assert can_auto is False

        # manual 허용 (total 7/10, 아직 여유)
        can_manual, _ = limiter.can_run_ai_pipeline(source_type="manual")
        assert can_manual is True

    def test_manual_blocked_at_total_limit(self, db_session):
        """총 한도 초과 시 수동도 차단"""
        manual_src = self._create_source(db_session, source_type="manual")

        limiter = RateLimiter(
            db_session, max_ai_drafts=3, manual_reserved=2,
        )
        for i in range(3):
            self._create_ai_draft(
                db_session, manual_src.id, body=f"Manual draft {i}",
            )

        can, msg = limiter.can_run_ai_pipeline(source_type="manual")
        assert can is False
        assert "한도 초과" in msg

    def test_daily_summary_includes_lanes(self, db_session):
        """일일 요약에 레인별 정보 포함"""
        limiter = RateLimiter(
            db_session, max_ai_drafts=20, manual_reserved=5,
        )
        summary = limiter.get_daily_summary()
        assert "ai_pipeline" in summary
        assert summary["ai_pipeline"]["limit"] == 20
        assert summary["ai_pipeline"]["auto_limit"] == 15
        assert summary["ai_pipeline"]["manual_reserved"] == 5


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
