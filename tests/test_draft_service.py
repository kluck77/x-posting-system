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


class TestPerformanceNote:
    """성과 메모(피드백 루프 1차) 테스트."""

    def _make_published_draft(self, db_session, source_item, hook="hook", body="body"):
        service = DraftService(db_session)
        draft = service.create_draft(
            source_item=source_item,
            hook=hook, body=body,
            category=ContentCategory.ECONOMY,
            risk_level=RiskLevel.LOW,
        )
        service.mark_published(draft.id, "x123", "https://x.com/x123")
        return draft

    def test_save_performance_note_first(self, db_session, source_item):
        """기존 메모 없을 때 [PERF] 태그로 저장된다."""
        service = DraftService(db_session)
        draft = self._make_published_draft(db_session, source_item)
        result = service.save_performance_note(draft.id, "좋아요 47개")
        assert result is not None
        assert result.manual_notes == "[PERF] 좋아요 47개"

    def test_save_performance_note_appends(self, db_session, source_item):
        """기존 메모가 있으면 줄바꿈 후 추가된다."""
        service = DraftService(db_session)
        draft = self._make_published_draft(db_session, source_item)
        draft.manual_notes = "사전 메모"
        db_session.commit()
        service.save_performance_note(draft.id, "팔로워 +3")
        db_session.refresh(draft)
        assert "사전 메모" in draft.manual_notes
        assert "[PERF] 팔로워 +3" in draft.manual_notes

    def test_save_performance_note_nonexistent_draft(self, db_session, source_item):
        """존재하지 않는 draft_id는 None 반환."""
        service = DraftService(db_session)
        result = service.save_performance_note(99999, "메모")
        assert result is None

    def test_get_published_with_perf_notes(self, db_session, source_item):
        """[PERF] 메모가 있는 게시 초안만 반환된다."""
        service = DraftService(db_session)
        d1 = self._make_published_draft(db_session, source_item, "hook1", "body1")
        d2 = self._make_published_draft(db_session, source_item, "hook2", "body2")
        service.save_performance_note(d1.id, "좋아요 30개")
        # d2는 메모 없음
        results = service.get_published_with_perf_notes()
        ids = [d.id for d in results]
        assert d1.id in ids
        assert d2.id not in ids

    def test_get_published_with_perf_notes_limit(self, db_session, source_item):
        """limit 인수가 적용된다."""
        service = DraftService(db_session)
        for i in range(4):
            d = self._make_published_draft(db_session, source_item, f"h{i}", f"b{i}")
            service.save_performance_note(d.id, f"메모{i}")
        results = service.get_published_with_perf_notes(limit=2)
        assert len(results) <= 2


class TestFormatPerfSummary:
    """format_perf_summary() 집계 요약 테스트."""

    def _make_published_with_perf(
        self, db_session, source_item, hook, body, perf_note, tags=None, fmt="single"
    ):
        service = DraftService(db_session)
        draft = service.create_draft(
            source_item=source_item,
            hook=hook, body=body,
            category=ContentCategory.ECONOMY,
            risk_level=RiskLevel.LOW,
        )
        draft.topic_tags = f'["{tags}"]' if tags else None
        draft.output_format = fmt
        db_session.commit()
        service.mark_published(draft.id, f"x{draft.id}", f"https://x.com/x{draft.id}")
        service.save_performance_note(draft.id, perf_note)
        return draft

    def test_returns_empty_when_no_perf_notes(self, db_session, source_item):
        """[PERF] 메모 없으면 빈 문자열 반환."""
        service = DraftService(db_session)
        result = service.format_perf_summary()
        assert result == ""

    def test_includes_category_count(self, db_session, source_item):
        """카테고리 집계가 요약에 포함된다."""
        self._make_published_with_perf(db_session, source_item, "h1", "b1", "좋아요 30개")
        result = DraftService(db_session).format_perf_summary()
        assert "카테고리" in result
        assert "economy" in result

    def test_includes_tag_count(self, db_session, source_item):
        """topic_tags 집계가 포함된다."""
        self._make_published_with_perf(
            db_session, source_item, "h1", "b1", "메모", tags="BOK"
        )
        result = DraftService(db_session).format_perf_summary()
        assert "BOK" in result

    def test_includes_recent_note_text(self, db_session, source_item):
        """최근 PERF 메모 원문이 포함된다."""
        self._make_published_with_perf(
            db_session, source_item, "h1", "b1", "팔로워 +5 좋음"
        )
        result = DraftService(db_session).format_perf_summary()
        assert "팔로워 +5 좋음" in result

    def test_days_filter(self, db_session, source_item):
        """days=0이면 과거 데이터 미포함."""
        self._make_published_with_perf(db_session, source_item, "h1", "b1", "메모")
        result = DraftService(db_session).format_perf_summary(days=0)
        assert result == ""
