"""
프리미엄 Korea Brief 후보 서비스 테스트 (Phase 3)
==================================================
PremiumCandidateService의 수집/랭킹/상태/메모/내보내기 검증.
"""

import json
import pytest
from datetime import datetime, timezone
# db_session fixture from conftest.py
from app.models.content import (
    Base, Draft, SourceItem, ContentCategory, RiskLevel, ApprovalStatus,
)
from app.services.premium_candidate_service import (
    PremiumCandidateService,
    PREMIUM_STATUSES,
    TARGET_READER_TYPES,
)


@pytest.fixture
def db(db_session):
    """테스트용 인메모리 DB 세션 (conftest.py의 db_session 재사용)."""
    return db_session


def _make_source(db, title="Test Source"):
    src = SourceItem(
        title=title, source_text="test text", source_type="manual",
        language="ko", created_at=datetime.now(timezone.utc),
    )
    db.add(src)
    db.commit()
    db.refresh(src)
    return src


def _make_premium_draft(
    db, source, hook="Premium Hook", score=60, status=None, note=None, reader=None,
):
    """프리미엄 후보 태그가 있는 테스트 드래프트 생성."""
    draft = Draft(
        source_item_id=source.id,
        hook=hook,
        body="Premium test body content",
        category=ContentCategory.ECONOMY,
        risk_level=RiskLevel.MEDIUM,
        approval_status=ApprovalStatus.PENDING,
        business_tags=json.dumps(["growth", "premium_candidate"]),
        monetization_score=score,
        premium_reason="Test premium reason",
        premium_status=status,
        premium_note=note,
        target_reader_type=reader,
        created_at=datetime.now(timezone.utc),
    )
    db.add(draft)
    db.commit()
    db.refresh(draft)
    return draft


def _make_regular_draft(db, source, hook="Regular Hook"):
    """프리미엄이 아닌 일반 드래프트 생성."""
    draft = Draft(
        source_item_id=source.id,
        hook=hook,
        body="Regular test body content",
        category=ContentCategory.SOCIETY,
        risk_level=RiskLevel.LOW,
        approval_status=ApprovalStatus.PENDING,
        business_tags=json.dumps(["growth"]),
        monetization_score=20,
        created_at=datetime.now(timezone.utc),
    )
    db.add(draft)
    db.commit()
    db.refresh(draft)
    return draft


# ─── 수집 테스트 ──────────────────────────────────────────────

class TestGetCandidates:
    def test_returns_premium_only(self, db):
        src = _make_source(db)
        premium = _make_premium_draft(db, src, score=70)
        regular = _make_regular_draft(db, src)

        svc = PremiumCandidateService(db)
        result = svc.get_candidates()
        ids = [d.id for d in result]
        assert premium.id in ids
        assert regular.id not in ids

    def test_sorted_by_score_desc(self, db):
        src = _make_source(db)
        low = _make_premium_draft(db, src, hook="Low", score=30)
        high = _make_premium_draft(db, src, hook="High", score=90)
        mid = _make_premium_draft(db, src, hook="Mid", score=60)

        svc = PremiumCandidateService(db)
        result = svc.get_candidates()
        scores = [d.monetization_score for d in result]
        assert scores == sorted(scores, reverse=True)

    def test_filter_by_status(self, db):
        src = _make_source(db)
        _make_premium_draft(db, src, status="new")
        _make_premium_draft(db, src, status="shortlisted")

        svc = PremiumCandidateService(db)
        result = svc.get_candidates(status="shortlisted")
        assert len(result) == 1
        assert result[0].premium_status == "shortlisted"

    def test_empty_result(self, db):
        svc = PremiumCandidateService(db)
        assert svc.get_candidates() == []

    def test_limit(self, db):
        src = _make_source(db)
        for i in range(5):
            _make_premium_draft(db, src, score=50 + i)

        svc = PremiumCandidateService(db)
        result = svc.get_candidates(limit=3)
        assert len(result) == 3


class TestGetCandidateById:
    def test_returns_premium_draft(self, db):
        src = _make_source(db)
        draft = _make_premium_draft(db, src)

        svc = PremiumCandidateService(db)
        result = svc.get_candidate_by_id(draft.id)
        assert result is not None
        assert result.id == draft.id

    def test_returns_none_for_regular(self, db):
        src = _make_source(db)
        draft = _make_regular_draft(db, src)

        svc = PremiumCandidateService(db)
        assert svc.get_candidate_by_id(draft.id) is None

    def test_returns_none_for_missing(self, db):
        svc = PremiumCandidateService(db)
        assert svc.get_candidate_by_id(9999) is None


class TestCountByStatus:
    def test_counts_correctly(self, db):
        src = _make_source(db)
        _make_premium_draft(db, src, status="new")
        _make_premium_draft(db, src, status="new")
        _make_premium_draft(db, src, status="shortlisted")

        svc = PremiumCandidateService(db)
        counts = svc.count_by_status()
        assert counts["new"] == 2
        assert counts["shortlisted"] == 1

    def test_none_status_counted_as_new(self, db):
        src = _make_source(db)
        _make_premium_draft(db, src, status=None)

        svc = PremiumCandidateService(db)
        counts = svc.count_by_status()
        assert counts.get("new", 0) == 1


# ─── 상태 관리 테스트 ──────────────────────────────────────────

class TestUpdateStatus:
    def test_valid_status_change(self, db):
        src = _make_source(db)
        draft = _make_premium_draft(db, src, status="new")

        svc = PremiumCandidateService(db)
        result = svc.update_status(draft.id, "reviewing")
        assert result is not None
        assert result.premium_status == "reviewing"
        assert result.premium_updated_at is not None

    def test_invalid_status_returns_none(self, db):
        src = _make_source(db)
        draft = _make_premium_draft(db, src, status="new")

        svc = PremiumCandidateService(db)
        assert svc.update_status(draft.id, "invalid_status") is None

    def test_non_premium_returns_none(self, db):
        src = _make_source(db)
        draft = _make_regular_draft(db, src)

        svc = PremiumCandidateService(db)
        assert svc.update_status(draft.id, "reviewing") is None

    def test_all_statuses_valid(self, db):
        src = _make_source(db)
        for status in PREMIUM_STATUSES:
            draft = _make_premium_draft(db, src, status="new")
            svc = PremiumCandidateService(db)
            result = svc.update_status(draft.id, status)
            assert result is not None
            assert result.premium_status == status


# ─── 메모 테스트 ──────────────────────────────────────────────

class TestSetNote:
    def test_save_note(self, db):
        src = _make_source(db)
        draft = _make_premium_draft(db, src)

        svc = PremiumCandidateService(db)
        result = svc.set_note(draft.id, "expat 노동 이슈 브리프에 적합")
        assert result is not None
        assert result.premium_note == "expat 노동 이슈 브리프에 적합"

    def test_note_truncated_at_500(self, db):
        src = _make_source(db)
        draft = _make_premium_draft(db, src)

        svc = PremiumCandidateService(db)
        long_note = "x" * 600
        result = svc.set_note(draft.id, long_note)
        assert len(result.premium_note) == 500

    def test_overwrite_note(self, db):
        src = _make_source(db)
        draft = _make_premium_draft(db, src, note="old note")

        svc = PremiumCandidateService(db)
        result = svc.set_note(draft.id, "new note")
        assert result.premium_note == "new note"

    def test_non_premium_returns_none(self, db):
        src = _make_source(db)
        draft = _make_regular_draft(db, src)

        svc = PremiumCandidateService(db)
        assert svc.set_note(draft.id, "note") is None


# ─── 대상 독자 테스트 ────────────────────────────────────────

class TestSetTargetReader:
    def test_set_reader(self, db):
        src = _make_source(db)
        draft = _make_premium_draft(db, src)

        svc = PremiumCandidateService(db)
        result = svc.set_target_reader(draft.id, "foreign_investors")
        assert result.target_reader_type == "foreign_investors"


# ─── 자동 초기화 테스트 ─────────────────────────────────────

class TestInitNewCandidates:
    def test_init_none_status(self, db):
        src = _make_source(db)
        _make_premium_draft(db, src, status=None)
        _make_premium_draft(db, src, status=None)
        _make_premium_draft(db, src, status="reviewing")

        svc = PremiumCandidateService(db)
        count = svc.init_new_candidates()
        assert count == 2

    def test_init_skips_existing(self, db):
        src = _make_source(db)
        _make_premium_draft(db, src, status="shortlisted")

        svc = PremiumCandidateService(db)
        count = svc.init_new_candidates()
        assert count == 0


# ─── 내보내기 테스트 ──────────────────────────────────────────

class TestExportCandidates:
    def test_export_returns_dicts(self, db):
        src = _make_source(db)
        _make_premium_draft(db, src, status="new", score=70)

        svc = PremiumCandidateService(db)
        result = svc.export_candidates()
        assert len(result) == 1
        item = result[0]
        assert "draft_id" in item
        assert "hook" in item
        assert "monetization_score" in item
        assert "premium_status" in item
        assert "premium_reason" in item
        assert "source_title" in item

    def test_export_filter_by_status(self, db):
        src = _make_source(db)
        _make_premium_draft(db, src, status="new")
        _make_premium_draft(db, src, status="shortlisted")

        svc = PremiumCandidateService(db)
        result = svc.export_candidates(status="shortlisted")
        assert len(result) == 1

    def test_export_empty(self, db):
        svc = PremiumCandidateService(db)
        assert svc.export_candidates() == []


# ─── 요약 테스트 ──────────────────────────────────────────────

class TestFormatSummary:
    def test_summary_no_candidates(self, db):
        svc = PremiumCandidateService(db)
        text = svc.format_summary()
        assert "없음" in text

    def test_summary_with_candidates(self, db):
        src = _make_source(db)
        _make_premium_draft(db, src, status="new", score=70)
        _make_premium_draft(db, src, status="shortlisted", score=80)

        svc = PremiumCandidateService(db)
        text = svc.format_summary()
        assert "2건" in text
        assert "신규" in text
        assert "후보 확정" in text


class TestFormatDetail:
    def test_detail_includes_key_info(self, db):
        src = _make_source(db)
        draft = _make_premium_draft(
            db, src, score=75, status="reviewing",
            note="좋은 후보", reader="foreign_investors",
        )

        svc = PremiumCandidateService(db)
        text = svc.format_candidate_detail(draft)
        assert str(draft.id) in text
        assert "75" in text
        assert "reviewing" in text
        assert "좋은 후보" in text
        assert "foreign_investors" in text


# ─── 상태 상수 테스트 ────────────────────────────────────────

class TestConstants:
    def test_premium_statuses_complete(self):
        expected = ("new", "reviewing", "shortlisted", "postponed", "rejected", "promoted")
        assert PREMIUM_STATUSES == expected

    def test_target_reader_types_nonempty(self):
        assert len(TARGET_READER_TYPES) >= 5
