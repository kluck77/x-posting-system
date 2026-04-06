"""
B2B 리서치 후보 서비스 테스트 (Phase 5-B2B)
==============================================
B2BCandidateService CRUD, 상태관리, 그룹핑, 내보내기 검증.
"""

import pytest
from datetime import datetime, timezone
from app.models.content import (
    Base, Draft, SourceItem, ContentCategory, RiskLevel, ApprovalStatus,
)
from app.services.b2b_candidate_service import (
    B2BCandidateService,
    B2B_STATUSES,
    B2B_TARGET_AUDIENCES,
    B2B_USE_CASES,
)


@pytest.fixture
def db(db_session):
    return db_session


def _make_source(db, title="B2B Test Source"):
    src = SourceItem(
        title=title, source_text="test text", source_type="manual",
        language="ko", created_at=datetime.now(timezone.utc),
    )
    db.add(src)
    db.commit()
    db.refresh(src)
    return src


def _make_b2b_draft(
    db, source, hook="B2B Hook", b2b_candidate=True,
    audience=None, use_case=None, status=None, note=None,
    score=None, premium_status=None,
):
    draft = Draft(
        source_item_id=source.id,
        hook=hook,
        body="B2B test body content about Korea regulations",
        category=ContentCategory.ECONOMY,
        risk_level=RiskLevel.LOW,
        approval_status=ApprovalStatus.PUBLISHED,
        b2b_candidate=b2b_candidate,
        b2b_target_audience=audience,
        b2b_use_case=use_case,
        b2b_status=status,
        b2b_note=note,
        monetization_score=score,
        premium_status=premium_status,
        created_at=datetime.now(timezone.utc),
    )
    db.add(draft)
    db.commit()
    db.refresh(draft)
    return draft


# ─── 상수 테스트 ──────────────────────────────────────────────

class TestConstants:
    def test_b2b_statuses(self):
        expected = ("new", "reviewing", "shortlisted", "postponed", "rejected", "promoted")
        assert B2B_STATUSES == expected

    def test_audiences_nonempty(self):
        assert len(B2B_TARGET_AUDIENCES) >= 5

    def test_use_cases_nonempty(self):
        assert len(B2B_USE_CASES) >= 5


# ─── 조회 테스트 ──────────────────────────────────────────────

class TestGetCandidates:
    def test_returns_b2b_only(self, db):
        src = _make_source(db)
        b2b = _make_b2b_draft(db, src, b2b_candidate=True)
        non_b2b = _make_b2b_draft(db, src, hook="Not B2B", b2b_candidate=False)

        svc = B2BCandidateService(db)
        result = svc.get_candidates()
        ids = [d.id for d in result]
        assert b2b.id in ids
        assert non_b2b.id not in ids

    def test_filter_by_status(self, db):
        src = _make_source(db)
        d1 = _make_b2b_draft(db, src, status="shortlisted")
        d2 = _make_b2b_draft(db, src, status="new")

        svc = B2BCandidateService(db)
        result = svc.get_candidates(status="shortlisted")
        assert len(result) == 1
        assert result[0].id == d1.id

    def test_limit(self, db):
        src = _make_source(db)
        for i in range(5):
            _make_b2b_draft(db, src, hook=f"B2B {i}")

        svc = B2BCandidateService(db)
        result = svc.get_candidates(limit=3)
        assert len(result) == 3

    def test_empty(self, db):
        svc = B2BCandidateService(db)
        assert svc.get_candidates() == []


class TestGetCandidateById:
    def test_found(self, db):
        src = _make_source(db)
        draft = _make_b2b_draft(db, src)

        svc = B2BCandidateService(db)
        assert svc.get_candidate_by_id(draft.id) is not None

    def test_non_b2b_returns_none(self, db):
        src = _make_source(db)
        draft = _make_b2b_draft(db, src, b2b_candidate=False)

        svc = B2BCandidateService(db)
        assert svc.get_candidate_by_id(draft.id) is None

    def test_missing_id(self, db):
        svc = B2BCandidateService(db)
        assert svc.get_candidate_by_id(9999) is None


class TestCountByStatus:
    def test_counts(self, db):
        src = _make_source(db)
        _make_b2b_draft(db, src, status="new")
        _make_b2b_draft(db, src, status="new")
        _make_b2b_draft(db, src, status="shortlisted")

        svc = B2BCandidateService(db)
        counts = svc.count_by_status()
        assert counts["new"] == 2
        assert counts["shortlisted"] == 1

    def test_null_status_counted_as_new(self, db):
        src = _make_source(db)
        _make_b2b_draft(db, src, status=None)

        svc = B2BCandidateService(db)
        counts = svc.count_by_status()
        assert counts.get("new", 0) == 1


# ─── 상태 변경 테스트 ─────────────────────────────────────────

class TestUpdateStatus:
    def test_valid_status(self, db):
        src = _make_source(db)
        draft = _make_b2b_draft(db, src)

        svc = B2BCandidateService(db)
        result = svc.update_status(draft.id, "reviewing")
        assert result is not None
        assert result.b2b_status == "reviewing"
        assert result.b2b_updated_at is not None

    def test_invalid_status(self, db):
        src = _make_source(db)
        draft = _make_b2b_draft(db, src)

        svc = B2BCandidateService(db)
        assert svc.update_status(draft.id, "invalid") is None

    def test_non_b2b_rejected(self, db):
        src = _make_source(db)
        draft = _make_b2b_draft(db, src, b2b_candidate=False)

        svc = B2BCandidateService(db)
        assert svc.update_status(draft.id, "reviewing") is None

    def test_all_statuses(self, db):
        src = _make_source(db)
        for s in B2B_STATUSES:
            draft = _make_b2b_draft(db, src, hook=f"Status {s}")
            svc = B2BCandidateService(db)
            result = svc.update_status(draft.id, s)
            assert result is not None
            assert result.b2b_status == s


# ─── 메모 테스트 ──────────────────────────────────────────────

class TestSetNote:
    def test_set_note(self, db):
        src = _make_source(db)
        draft = _make_b2b_draft(db, src)

        svc = B2BCandidateService(db)
        result = svc.set_note(draft.id, "규제 브리프 적합")
        assert result.b2b_note == "규제 브리프 적합"

    def test_note_truncated(self, db):
        src = _make_source(db)
        draft = _make_b2b_draft(db, src)

        svc = B2BCandidateService(db)
        result = svc.set_note(draft.id, "x" * 600)
        assert len(result.b2b_note) == 500

    def test_non_b2b_rejected(self, db):
        src = _make_source(db)
        draft = _make_b2b_draft(db, src, b2b_candidate=False)

        svc = B2BCandidateService(db)
        assert svc.set_note(draft.id, "test") is None


# ─── 대상 독자 / 활용 사례 테스트 ─────────────────────────────

class TestSetTargetAudience:
    def test_set_audience(self, db):
        src = _make_source(db)
        draft = _make_b2b_draft(db, src)

        svc = B2BCandidateService(db)
        result = svc.set_target_audience(draft.id, "investors")
        assert result.b2b_target_audience == "investors"

    def test_custom_audience(self, db):
        src = _make_source(db)
        draft = _make_b2b_draft(db, src)

        svc = B2BCandidateService(db)
        result = svc.set_target_audience(draft.id, "crypto_funds")
        assert result.b2b_target_audience == "crypto_funds"


class TestSetUseCase:
    def test_set_use_case(self, db):
        src = _make_source(db)
        draft = _make_b2b_draft(db, src)

        svc = B2BCandidateService(db)
        result = svc.set_use_case(draft.id, "regulation_brief")
        assert result.b2b_use_case == "regulation_brief"


# ─── 초기화 테스트 ────────────────────────────────────────────

class TestInitNewCandidates:
    def test_inits_null_status(self, db):
        src = _make_source(db)
        _make_b2b_draft(db, src, status=None)
        _make_b2b_draft(db, src, status=None)
        _make_b2b_draft(db, src, status="reviewing")

        svc = B2BCandidateService(db)
        count = svc.init_new_candidates()
        assert count == 2

    def test_skips_existing_status(self, db):
        src = _make_source(db)
        _make_b2b_draft(db, src, status="shortlisted")

        svc = B2BCandidateService(db)
        count = svc.init_new_candidates()
        assert count == 0


# ─── 그룹핑 테스트 ────────────────────────────────────────────

class TestGetByAudience:
    def test_filter_by_audience(self, db):
        src = _make_source(db)
        _make_b2b_draft(db, src, audience="investors")
        _make_b2b_draft(db, src, audience="investors")
        _make_b2b_draft(db, src, audience="journalists")

        svc = B2BCandidateService(db)
        result = svc.get_by_audience("investors")
        assert len(result) == 2

    def test_empty_audience(self, db):
        svc = B2BCandidateService(db)
        assert svc.get_by_audience("nonexistent") == []


class TestGetByUseCase:
    def test_filter_by_use_case(self, db):
        src = _make_source(db)
        _make_b2b_draft(db, src, use_case="regulation_brief")
        _make_b2b_draft(db, src, use_case="regulation_brief")
        _make_b2b_draft(db, src, use_case="election_context")

        svc = B2BCandidateService(db)
        result = svc.get_by_use_case("regulation_brief")
        assert len(result) == 2

    def test_empty_use_case(self, db):
        svc = B2BCandidateService(db)
        assert svc.get_by_use_case("nonexistent") == []


class TestGroupByAudience:
    def test_groups(self, db):
        src = _make_source(db)
        _make_b2b_draft(db, src, audience="investors")
        _make_b2b_draft(db, src, audience="investors")
        _make_b2b_draft(db, src, audience="policy_teams")
        _make_b2b_draft(db, src, audience=None)

        svc = B2BCandidateService(db)
        groups = svc.group_by_audience()
        assert groups["investors"] == 2
        assert groups["policy_teams"] == 1
        assert None not in groups

    def test_empty(self, db):
        svc = B2BCandidateService(db)
        assert svc.group_by_audience() == {}


class TestGroupByUseCase:
    def test_groups(self, db):
        src = _make_source(db)
        _make_b2b_draft(db, src, use_case="regulation_brief")
        _make_b2b_draft(db, src, use_case="regulation_brief")
        _make_b2b_draft(db, src, use_case="election_context")

        svc = B2BCandidateService(db)
        groups = svc.group_by_use_case()
        assert groups["regulation_brief"] == 2
        assert groups["election_context"] == 1


# ─── 내보내기 테스트 ──────────────────────────────────────────

class TestExportCandidates:
    def test_export_basic(self, db):
        src = _make_source(db, title="Regulation Source")
        _make_b2b_draft(
            db, src,
            audience="investors", use_case="regulation_brief",
            note="좋은 후보", status="shortlisted", score=75,
        )

        svc = B2BCandidateService(db)
        items = svc.export_candidates()
        assert len(items) == 1
        item = items[0]
        assert item["b2b_target_audience"] == "investors"
        assert item["b2b_use_case"] == "regulation_brief"
        assert item["b2b_note"] == "좋은 후보"
        assert item["b2b_status"] == "shortlisted"
        assert item["monetization_score"] == 75
        assert item["source_title"] == "Regulation Source"

    def test_export_with_premium_linkage(self, db):
        src = _make_source(db)
        _make_b2b_draft(db, src, premium_status="reviewing")

        svc = B2BCandidateService(db)
        items = svc.export_candidates()
        assert items[0]["premium_linkage"] is not None
        assert items[0]["premium_linkage"]["premium_status"] == "reviewing"

    def test_export_empty(self, db):
        svc = B2BCandidateService(db)
        assert svc.export_candidates() == []

    def test_export_filter_by_status(self, db):
        src = _make_source(db)
        _make_b2b_draft(db, src, status="shortlisted")
        _make_b2b_draft(db, src, status="new")

        svc = B2BCandidateService(db)
        items = svc.export_candidates(status="shortlisted")
        assert len(items) == 1


# ─── 포맷 테스트 ──────────────────────────────────────────────

class TestFormatSummary:
    def test_empty(self, db):
        svc = B2BCandidateService(db)
        text = svc.format_summary()
        assert "없음" in text

    def test_with_data(self, db):
        src = _make_source(db)
        _make_b2b_draft(db, src, status="new")
        _make_b2b_draft(db, src, status="shortlisted")

        svc = B2BCandidateService(db)
        text = svc.format_summary()
        assert "B2B" in text
        assert "2건" in text

    def test_summary_includes_audience_and_usecase(self, db):
        src = _make_source(db)
        _make_b2b_draft(db, src, status="new", audience="investors", use_case="regulation_brief")
        _make_b2b_draft(db, src, status="new", audience="investors", use_case="election_context")

        svc = B2BCandidateService(db)
        text = svc.format_summary()
        assert "investors" in text
        assert "regulation_brief" in text


class TestFormatCandidateDetail:
    def test_includes_key_info(self, db):
        src = _make_source(db)
        draft = _make_b2b_draft(
            db, src,
            hook="Korea Labor Law Changes",
            audience="policy_teams",
            use_case="labor_market_snapshot",
            note="Q2 리포트 후보",
            status="reviewing",
            score=80,
            premium_status="shortlisted",
        )

        svc = B2BCandidateService(db)
        text = svc.format_candidate_detail(draft)
        assert str(draft.id) in text
        assert "Korea Labor Law" in text
        assert "policy_teams" in text
        assert "labor_market_snapshot" in text
        assert "Q2 리포트 후보" in text
        assert "검토중" in text
        assert "80" in text
        assert "프리미엄" in text
