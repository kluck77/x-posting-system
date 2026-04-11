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

        # 25 시간 전 = 하루 이상 전이므로 어제 (KST/UTC 모두)
        yesterday = datetime.now(timezone.utc) - timedelta(hours=25)
        _create_draft(db_session, source.id, created_at=yesterday)

        allowed, msg = limiter.can_create_draft()
        assert allowed is True


class TestRateLimiterKSTAndKoOnlyFilter:
    """
    _today_start() KST 정상화 + KO_ONLY_BODY_PREFIX 필터 정상화 검증.

    과거 버그:
    - _today_start() 가 UTC 자정 + aware datetime 을 반환해 naive DB 컬럼과
      혼합 비교됨. KST 오늘 새벽~오전 생성 드래프트가 '어제' 로 빠지거나 반대로.
    - KO_ONLY_BODY_PREFIX 가 '한국어 전용 라인 처리' 였는데 orchestrator 가 실제로
      쓰는 body 는 'KO-only pipeline (English draft skipped). domain=...' 이라
      필터가 완전히 어긋나, KO-only 드래프트가 전부 AI 파이프라인 카운트로 잡혀
      매일 20 한도를 빠르게 소진했다.
    """

    def test_today_start_returns_naive_utc(self, db_session):
        """_today_start() 는 naive UTC datetime 을 반환해야 한다."""
        from app.services.rate_limiter import KST

        limiter = RateLimiter(db_session)
        start = limiter._today_start()

        # naive (tzinfo 없음) 이어야 DB 비교 시 혼합 경고가 안 난다
        assert start.tzinfo is None

        # KST 오늘 00:00 의 UTC 환산값과 일치해야 한다
        now_kst = datetime.now(KST)
        expected_kst_midnight = now_kst.replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        expected_naive_utc = (
            expected_kst_midnight.astimezone(timezone.utc).replace(tzinfo=None)
        )
        # 초 단위 스큐 허용
        assert abs((start - expected_naive_utc).total_seconds()) < 2

    def test_ko_only_draft_excluded_from_ai_count(self, db_session):
        """
        orchestrator 가 쓰는 실제 KO-only body 를 가진 드래프트는
        AI 파이프라인 카운트에서 제외되어야 한다.
        """
        source = _create_source(db_session)
        limiter = RateLimiter(db_session, max_ai_drafts=5)

        # orchestrator.py line 255 에서 쓰는 포맷 그대로
        _create_draft(
            db_session, source.id,
            body="KO-only pipeline (English draft skipped). domain=금융",
        )
        _create_draft(
            db_session, source.id,
            body="KO-only pipeline (English draft skipped). domain=크립토",
        )

        # KO-only 만 있으므로 AI 카운트는 0
        assert limiter.get_today_ai_draft_count() == 0

        allowed, msg = limiter.can_run_ai_pipeline(source_type="manual")
        assert allowed is True

    def test_real_ai_draft_counted(self, db_session):
        """실제 AI 파이프라인을 거친 드래프트는 카운트에 포함된다."""
        source = _create_source(db_session)
        limiter = RateLimiter(db_session, max_ai_drafts=5)

        _create_draft(
            db_session, source.id,
            body="한국은행이 기준금리를 동결했다. 시장은 안정적.",
        )

        assert limiter.get_today_ai_draft_count() == 1

    def test_mixed_drafts_only_ai_counted(self, db_session):
        """KO-only 와 AI 드래프트가 섞여 있을 때 AI 만 카운트."""
        source = _create_source(db_session)
        limiter = RateLimiter(db_session, max_ai_drafts=5)

        # 5 개의 KO-only
        for i in range(5):
            _create_draft(
                db_session, source.id,
                body=f"KO-only pipeline (English draft skipped). domain=금융",
                hook=f"ko-only-{i}",
            )
        # 2 개의 AI 파이프라인 드래프트
        for i in range(2):
            _create_draft(
                db_session, source.id,
                body=f"실제 AI 리뷰 결과 본문 {i}",
                hook=f"ai-{i}",
            )

        # AI 카운트는 2 여야 한다 (KO-only 5 개는 제외)
        assert limiter.get_today_ai_draft_count() == 2

        # max_ai_drafts=5 이므로 여전히 여유 있음
        allowed, _ = limiter.can_run_ai_pipeline(source_type="manual")
        assert allowed is True

    def test_yesterday_ai_draft_not_counted(self, db_session):
        """25시간 전 AI 드래프트는 오늘 카운트에 들어가지 않는다."""
        source = _create_source(db_session)
        limiter = RateLimiter(db_session, max_ai_drafts=1)

        yesterday = datetime.now(timezone.utc) - timedelta(hours=25)
        _create_draft(
            db_session, source.id,
            body="어제 생성된 AI 드래프트 본문",
            created_at=yesterday,
        )

        assert limiter.get_today_ai_draft_count() == 0

        allowed, _ = limiter.can_run_ai_pipeline(source_type="manual")
        assert allowed is True

    def test_rate_limit_not_blocked_by_old_ko_only_drafts(self, db_session):
        """
        회귀 테스트: 과거 대량의 KO-only 드래프트가 DB 에 있어도
        오늘의 rate limit 를 소진하지 않아야 한다.

        이전 버그의 정확한 재현:
        - KO_ONLY_BODY_PREFIX 필터가 어긋나 KO-only 가 카운트됨
        - _today_start() 가 UTC 기준이라 KST 오늘 새벽 드래프트가 누락됨
        """
        source = _create_source(db_session)
        limiter = RateLimiter(db_session, max_ai_drafts=20)

        # 오늘 KO-only 드래프트 50개 (KO-only 는 AI 카운트 제외되어야 함)
        for i in range(50):
            _create_draft(
                db_session, source.id,
                body="KO-only pipeline (English draft skipped). domain=금융",
                hook=f"ko-{i}",
            )

        # 여전히 AI 파이프라인 사용 가능해야 함
        allowed, msg = limiter.can_run_ai_pipeline(source_type="manual")
        assert allowed is True, f"KO-only drafts blocked AI pipeline: {msg}"
        assert limiter.get_today_ai_draft_count() == 0


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
