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
        """topic_tags 집계가 포함된다 (소문자 정규화)."""
        self._make_published_with_perf(
            db_session, source_item, "h1", "b1", "메모", tags="BOK"
        )
        result = DraftService(db_session).format_perf_summary()
        assert "bok" in result

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

    # v2 패턴 분석 테스트

    def _make_published_no_perf(self, db_session, source_item, hook, body, tags=None):
        """[PERF] 메모 없이 게시만 한 초안 (분모 데이터)."""
        service = DraftService(db_session)
        draft = service.create_draft(
            source_item=source_item,
            hook=hook, body=body,
            category=ContentCategory.ECONOMY,
            risk_level=RiskLevel.LOW,
        )
        draft.topic_tags = f'["{tags}"]' if tags else None
        db_session.commit()
        service.mark_published(draft.id, f"x{draft.id}", f"https://x.com/x{draft.id}")
        return draft

    def test_increase_candidate_shown(self, db_session, source_item):
        """[PERF] 비율이 높은 태그가 늘릴 후보에 포함된다."""
        # BOK 태그: 2회 게시 중 2회 모두 [PERF] → 비율 100%
        self._make_published_with_perf(db_session, source_item, "h1", "b1", "좋아요", tags="bok")
        self._make_published_with_perf(db_session, source_item, "h2", "b2", "리트윗", tags="bok")
        result = DraftService(db_session).format_perf_summary()
        assert "늘릴 후보" in result
        assert "bok" in result

    def test_decrease_candidate_shown(self, db_session, source_item):
        """전체에서 2회 이상이지만 [PERF] 없는 태그가 줄일 후보에 포함된다."""
        # "crypto" 태그: 3회 게시지만 [PERF] 0건
        self._make_published_no_perf(db_session, source_item, "h3", "b3", tags="crypto")
        self._make_published_no_perf(db_session, source_item, "h4", "b4", tags="crypto")
        self._make_published_no_perf(db_session, source_item, "h5", "b5", tags="crypto")
        # 다른 태그에 [PERF]가 있어야 perf_drafts 쿼리가 결과를 반환함
        self._make_published_with_perf(db_session, source_item, "h6", "b6", "좋음", tags="bok")
        result = DraftService(db_session).format_perf_summary()
        assert "줄일 후보" in result
        assert "crypto" in result

    def test_no_pattern_section_when_tags_absent(self, db_session, source_item):
        """태그가 전혀 없으면 패턴 라인이 나타나지 않는다."""
        self._make_published_with_perf(db_session, source_item, "h1", "b1", "좋음")
        result = DraftService(db_session).format_perf_summary()
        assert "늘릴 후보" not in result
        assert "줄일 후보" not in result


class TestGetRecentOperatorHints:
    """get_recent_operator_hints() 테스트."""

    def _make_draft_with_note(self, db_session, source_item, hook, body, note,
                               status=ApprovalStatus.PUBLISHED):
        service = DraftService(db_session)
        draft = service.create_draft(
            source_item=source_item,
            hook=hook, body=body,
            category=ContentCategory.ECONOMY,
            risk_level=RiskLevel.LOW,
        )
        draft.manual_notes = note
        if status == ApprovalStatus.PUBLISHED:
            draft.approval_status = ApprovalStatus.PUBLISHED
        elif status == ApprovalStatus.APPROVED:
            draft.approval_status = ApprovalStatus.APPROVED
        db_session.commit()
        return draft

    def test_returns_empty_when_no_notes(self, db_session, source_item):
        """notes 없으면 빈 리스트 반환."""
        result = DraftService(db_session).get_recent_operator_hints()
        assert result == []

    def test_returns_note_from_published_draft(self, db_session, source_item):
        """published 초안의 manual_notes가 반환된다."""
        self._make_draft_with_note(
            db_session, source_item, "h1", "b1", "경제 충격 각도로 써줘"
        )
        result = DraftService(db_session).get_recent_operator_hints()
        assert len(result) == 1
        assert "경제 충격 각도로 써줘" in result[0]

    def test_returns_note_from_approved_draft(self, db_session, source_item):
        """approved 초안의 notes도 포함된다."""
        self._make_draft_with_note(
            db_session, source_item, "h1", "b1", "approved 힌트",
            status=ApprovalStatus.APPROVED,
        )
        result = DraftService(db_session).get_recent_operator_hints()
        assert any("approved 힌트" in h for h in result)

    def test_excludes_perf_lines(self, db_session, source_item):
        """[PERF] 접두어 라인은 제외된다."""
        self._make_draft_with_note(
            db_session, source_item, "h1", "b1", "[PERF] 좋아요 30개"
        )
        result = DraftService(db_session).get_recent_operator_hints()
        assert result == []

    def test_mixed_notes_returns_non_perf_only(self, db_session, source_item):
        """[PERF] 라인과 일반 라인이 섞인 경우 일반 라인만 수집."""
        self._make_draft_with_note(
            db_session, source_item, "h1", "b1",
            "다음엔 통화정책 각도로\n[PERF] 좋아요 10개"
        )
        result = DraftService(db_session).get_recent_operator_hints()
        assert len(result) == 1
        assert "통화정책" in result[0]
        assert "[PERF]" not in result[0]

    def test_respects_limit(self, db_session, source_item):
        """limit 파라미터가 적용된다."""
        for i in range(5):
            self._make_draft_with_note(
                db_session, source_item, f"h{i}", f"b{i}", f"힌트{i}"
            )
        result = DraftService(db_session).get_recent_operator_hints(limit=2)
        assert len(result) <= 2

    def test_truncates_long_notes(self, db_session, source_item):
        """120자 초과 메모는 잘린다."""
        long_note = "A" * 200
        self._make_draft_with_note(db_session, source_item, "h1", "b1", long_note)
        result = DraftService(db_session).get_recent_operator_hints()
        assert len(result) == 1
        assert len(result[0]) <= 120

    # v2 [HINT] prefix 테스트

    def test_hint_prefix_returned_without_prefix(self, db_session, source_item):
        """[HINT] 접두어는 제거되고 텍스트만 반환된다."""
        self._make_draft_with_note(
            db_session, source_item, "h1", "b1", "[HINT] 통화정책 충격 각도로 써줘"
        )
        result = DraftService(db_session).get_recent_operator_hints()
        assert len(result) == 1
        assert "통화정책 충격 각도로 써줘" in result[0]
        assert "[HINT]" not in result[0]

    def test_hint_preferred_over_plain_note(self, db_session, source_item):
        """[HINT] 라인이 있으면 일반 메모보다 우선 선택된다."""
        # draft A: 일반 메모
        self._make_draft_with_note(
            db_session, source_item, "h1", "b1", "그냥 메모입니다"
        )
        # draft B: [HINT] 메모
        self._make_draft_with_note(
            db_session, source_item, "h2", "b2", "[HINT] 반드시 반영할 힌트"
        )
        result = DraftService(db_session).get_recent_operator_hints(limit=1)
        assert len(result) == 1
        assert "반드시 반영할 힌트" in result[0]

    def test_fallback_to_plain_when_no_hint(self, db_session, source_item):
        """[HINT]가 없으면 v1처럼 일반 메모가 fallback으로 반환된다."""
        self._make_draft_with_note(
            db_session, source_item, "h1", "b1", "일반 운영 메모"
        )
        result = DraftService(db_session).get_recent_operator_hints()
        assert len(result) == 1
        assert "일반 운영 메모" in result[0]

    def test_hint_fills_first_plain_fills_rest(self, db_session, source_item):
        """[HINT] 1개 + 일반 메모로 limit=2를 채운다."""
        self._make_draft_with_note(
            db_session, source_item, "h1", "b1", "[HINT] 장기 힌트"
        )
        self._make_draft_with_note(
            db_session, source_item, "h2", "b2", "일반 메모"
        )
        result = DraftService(db_session).get_recent_operator_hints(limit=2)
        assert len(result) == 2
        assert any("장기 힌트" in r for r in result)
        assert any("일반 메모" in r for r in result)

    def test_hint_and_perf_in_same_note(self, db_session, source_item):
        """같은 manual_notes 안에 [HINT]와 [PERF]가 함께 있는 경우."""
        self._make_draft_with_note(
            db_session, source_item, "h1", "b1",
            "[HINT] 장기 스타일 힌트\n[PERF] 좋아요 50개"
        )
        result = DraftService(db_session).get_recent_operator_hints()
        assert len(result) == 1
        assert "장기 스타일 힌트" in result[0]
        assert "[PERF]" not in result[0]

    # /hint 명령 저장 형식 호환 테스트

    def test_hint_command_format_compatible(self, db_session, source_item):
        """/hint가 저장하는 '[HINT] <text>' 형식이 get_recent_operator_hints()에서 정상 수집된다."""
        # /hint 42 항상 통화정책 각도로 써줘  →  "[HINT] 항상 통화정책 각도로 써줘"
        hint_text = "[HINT] " + "항상 통화정책 각도로 써줘"
        self._make_draft_with_note(db_session, source_item, "h1", "b1", hint_text)
        result = DraftService(db_session).get_recent_operator_hints()
        assert len(result) == 1
        assert "항상 통화정책 각도로 써줘" in result[0]
        assert result[0].startswith("[HINT]") is False  # prefix 제거 확인

    def test_hint_command_max_length(self, db_session, source_item):
        """/hint의 prefix 포함 500자 이내 저장 — 493자 본문 + '[HINT] ' = 500자."""
        body = "A" * 493
        hint_text = "[HINT] " + body
        assert len(hint_text) == 500
        self._make_draft_with_note(db_session, source_item, "h1", "b1", hint_text)
        result = DraftService(db_session).get_recent_operator_hints()
        assert len(result) == 1
        assert len(result[0]) <= 120  # 수집 시 120자로 잘림


class TestGetHintLinesWithDraftId:
    """get_hint_lines_with_draft_id() — /hints 조회용 read path 테스트."""

    def _make_draft_with_note(self, db_session, source_item, hook, body, note,
                               status=ApprovalStatus.PUBLISHED):
        service = DraftService(db_session)
        draft = service.create_draft(
            source_item=source_item,
            hook=hook, body=body,
            category=ContentCategory.ECONOMY,
            risk_level=RiskLevel.LOW,
        )
        draft.manual_notes = note
        draft.approval_status = status
        db_session.commit()
        return draft

    def test_returns_empty_when_no_hints(self, db_session, source_item):
        """[HINT]가 없으면 빈 리스트."""
        result = DraftService(db_session).get_hint_lines_with_draft_id()
        assert result == []

    def test_returns_draft_id_and_text(self, db_session, source_item):
        """(draft_id, text) 튜플 반환, prefix 제거 확인."""
        d = self._make_draft_with_note(
            db_session, source_item, "h1", "b1", "[HINT] 통화정책 각도로"
        )
        result = DraftService(db_session).get_hint_lines_with_draft_id()
        assert len(result) == 1
        draft_id, text = result[0]
        assert draft_id == d.id
        assert text == "통화정책 각도로"

    def test_excludes_plain_and_perf_notes(self, db_session, source_item):
        """일반 메모와 [PERF] 라인은 반환되지 않는다."""
        self._make_draft_with_note(db_session, source_item, "h1", "b1", "일반 메모")
        self._make_draft_with_note(db_session, source_item, "h2", "b2", "[PERF] 좋아요 10개")
        result = DraftService(db_session).get_hint_lines_with_draft_id()
        assert result == []

    def test_multiple_hint_lines_per_draft(self, db_session, source_item):
        """초안 1개에 [HINT]가 여러 줄이면 모두 수집된다."""
        self._make_draft_with_note(
            db_session, source_item, "h1", "b1",
            "[HINT] 힌트A\n[HINT] 힌트B\n[PERF] 성과메모"
        )
        result = DraftService(db_session).get_hint_lines_with_draft_id()
        assert len(result) == 2
        texts = [t for _, t in result]
        assert "힌트A" in texts
        assert "힌트B" in texts

    def test_respects_limit(self, db_session, source_item):
        """limit 파라미터가 적용된다."""
        for i in range(5):
            self._make_draft_with_note(
                db_session, source_item, f"h{i}", f"b{i}", f"[HINT] 힌트{i}"
            )
        result = DraftService(db_session).get_hint_lines_with_draft_id(limit=3)
        assert len(result) <= 3


class TestClearHintLines:
    """clear_hint_lines() 테스트."""

    def _make_draft_with_note(self, db_session, source_item, hook, body, note):
        service = DraftService(db_session)
        draft = service.create_draft(
            source_item=source_item,
            hook=hook, body=body,
            category=ContentCategory.ECONOMY,
            risk_level=RiskLevel.LOW,
        )
        draft.manual_notes = note
        draft.approval_status = ApprovalStatus.PUBLISHED
        db_session.commit()
        return draft

    def test_returns_none_for_unknown_draft(self, db_session, source_item):
        """없는 draft_id면 None 반환."""
        result = DraftService(db_session).clear_hint_lines(99999)
        assert result is None

    def test_removes_hint_lines(self, db_session, source_item):
        """[HINT] 라인이 제거된다."""
        d = self._make_draft_with_note(
            db_session, source_item, "h1", "b1", "[HINT] 통화정책 각도로"
        )
        DraftService(db_session).clear_hint_lines(d.id)
        db_session.refresh(d)
        assert d.manual_notes is None or "[HINT]" not in (d.manual_notes or "")

    def test_preserves_plain_notes(self, db_session, source_item):
        """일반 메모는 유지된다."""
        d = self._make_draft_with_note(
            db_session, source_item, "h1", "b1",
            "[HINT] 장기 힌트\n일반 운영 메모"
        )
        DraftService(db_session).clear_hint_lines(d.id)
        db_session.refresh(d)
        assert "일반 운영 메모" in (d.manual_notes or "")
        assert "[HINT]" not in (d.manual_notes or "")

    def test_preserves_perf_lines(self, db_session, source_item):
        """[PERF] 라인은 유지된다."""
        d = self._make_draft_with_note(
            db_session, source_item, "h1", "b1",
            "[HINT] 장기 힌트\n[PERF] 좋아요 30개"
        )
        DraftService(db_session).clear_hint_lines(d.id)
        db_session.refresh(d)
        assert "[PERF] 좋아요 30개" in (d.manual_notes or "")
        assert "[HINT]" not in (d.manual_notes or "")

    def test_no_hint_lines_is_noop(self, db_session, source_item):
        """[HINT]가 없으면 기존 notes 그대로 유지."""
        d = self._make_draft_with_note(
            db_session, source_item, "h1", "b1", "일반 메모만"
        )
        DraftService(db_session).clear_hint_lines(d.id)
        db_session.refresh(d)
        assert d.manual_notes == "일반 메모만"

    def test_hint_no_longer_returned_after_clear(self, db_session, source_item):
        """clear 후 get_hint_lines_with_draft_id()에서 해당 draft가 제외된다."""
        d = self._make_draft_with_note(
            db_session, source_item, "h1", "b1", "[HINT] 지울 힌트"
        )
        service = DraftService(db_session)
        assert len(service.get_hint_lines_with_draft_id()) == 1
        service.clear_hint_lines(d.id)
        assert service.get_hint_lines_with_draft_id() == []


class TestFormatHintImpactSummary:
    """format_hint_impact_summary() — [HINT]×[PERF] 공존 집계 테스트."""

    def _make_published(self, db_session, source_item, hook, body, notes):
        service = DraftService(db_session)
        draft = service.create_draft(
            source_item=source_item,
            hook=hook, body=body,
            category=ContentCategory.ECONOMY,
            risk_level=RiskLevel.LOW,
        )
        draft.manual_notes = notes
        db_session.commit()
        service.mark_published(draft.id, f"x{draft.id}", f"https://x.com/{draft.id}")
        return draft

    def test_returns_empty_when_no_annotated_drafts(self, db_session, source_item):
        """notes 없으면 빈 문자열."""
        result = DraftService(db_session).format_hint_impact_summary()
        assert result == ""

    def test_counts_both_bucket(self, db_session, source_item):
        """[HINT]+[PERF] 공존 draft는 '성과 확인 + 힌트화' 버킷에 집계된다."""
        self._make_published(
            db_session, source_item, "h1", "b1",
            "[HINT] 통화정책 각도\n[PERF] 좋아요 30개"
        )
        result = DraftService(db_session).format_hint_impact_summary()
        assert "성과 확인 + 힌트화" in result
        assert "1건" in result

    def test_counts_perf_only_bucket(self, db_session, source_item):
        """[PERF]만 있는 draft는 '성과만 기록' 버킷에 집계된다."""
        self._make_published(
            db_session, source_item, "h1", "b1", "[PERF] 리트윗 5개"
        )
        result = DraftService(db_session).format_hint_impact_summary()
        assert "성과만 기록" in result

    def test_counts_hint_only_bucket(self, db_session, source_item):
        """[HINT]만 있는 draft는 '힌트만 있음' 버킷에 집계된다."""
        self._make_published(
            db_session, source_item, "h1", "b1", "[HINT] 짧게 써줘"
        )
        result = DraftService(db_session).format_hint_impact_summary()
        assert "힌트만 있음" in result

    def test_plain_notes_excluded_from_all_buckets(self, db_session, source_item):
        """일반 메모만 있는 draft는 어느 버킷에도 포함되지 않아 빈 문자열 반환."""
        self._make_published(
            db_session, source_item, "h1", "b1", "그냥 운영 메모"
        )
        result = DraftService(db_session).format_hint_impact_summary()
        assert result == ""

    def test_days_filter(self, db_session, source_item):
        """days=0이면 어떤 draft도 포함되지 않아 빈 문자열 반환."""
        self._make_published(
            db_session, source_item, "h1", "b1",
            "[HINT] 힌트\n[PERF] 성과"
        )
        result = DraftService(db_session).format_hint_impact_summary(days=0)
        assert result == ""
