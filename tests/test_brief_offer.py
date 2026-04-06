"""
Premium Korea Brief 오퍼 서비스 테스트
========================================
BriefOfferService CRUD, 상태관리, 내보내기, 포맷 검증.
"""

import json
import pytest
from datetime import datetime, timezone
from app.models.content import (
    Base, Draft, SourceItem, ContentCategory, RiskLevel, ApprovalStatus,
)
from app.services.brief_offer_service import (
    BriefOfferService,
    BRIEF_STATUSES,
    BRIEF_TYPES,
    BRIEF_TARGET_READERS,
    BRIEF_PRICE_TIERS,
)


@pytest.fixture
def db(db_session):
    return db_session


def _make_source(db, title="Brief Test Source"):
    src = SourceItem(
        title=title, source_text="test text", source_type="manual",
        language="ko", created_at=datetime.now(timezone.utc),
    )
    db.add(src)
    db.commit()
    db.refresh(src)
    return src


def _make_premium_draft(
    db, source, hook="Premium Hook",
    premium_status=None, premium_note=None, premium_reason=None,
    brief_type=None, brief_price_tier=None, brief_summary_note=None,
    target_reader=None, score=None, b2b=False,
):
    tags = json.dumps(["premium_candidate", "growth"])
    draft = Draft(
        source_item_id=source.id,
        hook=hook,
        body="Premium test body about Korea policy analysis",
        category=ContentCategory.POLICY,
        risk_level=RiskLevel.LOW,
        approval_status=ApprovalStatus.PUBLISHED,
        business_tags=tags,
        monetization_score=score,
        premium_status=premium_status,
        premium_note=premium_note,
        premium_reason=premium_reason,
        brief_type=brief_type,
        brief_price_tier=brief_price_tier,
        brief_summary_note=brief_summary_note,
        target_reader_type=target_reader,
        b2b_candidate=b2b,
        created_at=datetime.now(timezone.utc),
    )
    db.add(draft)
    db.commit()
    db.refresh(draft)
    return draft


# ─── 상수 테스트 ──────────────────────────────────────────────

class TestConstants:
    def test_brief_statuses(self):
        expected = ("new", "reviewing", "shortlisted", "drafted",
                    "ready", "postponed", "rejected", "promoted")
        assert BRIEF_STATUSES == expected

    def test_brief_types(self):
        expected = ("weekly_brief", "policy_brief", "market_brief",
                    "issue_brief", "explainer_pack", "special_report")
        assert BRIEF_TYPES == expected

    def test_brief_readers(self):
        expected = ("global_readers", "expats", "investors",
                    "journalists", "policy_watchers", "researchers")
        assert BRIEF_TARGET_READERS == expected

    def test_brief_tiers(self):
        assert BRIEF_PRICE_TIERS == ("low", "mid", "premium")

    def test_statuses_include_drafted_and_ready(self):
        assert "drafted" in BRIEF_STATUSES
        assert "ready" in BRIEF_STATUSES


# ─── 조회 테스트 ──────────────────────────────────────────────

class TestGetBriefs:
    def test_get_briefs_returns_premium_candidates(self, db):
        src = _make_source(db)
        _make_premium_draft(db, src, hook="Brief 1", score=80)
        _make_premium_draft(db, src, hook="Brief 2", score=90)
        svc = BriefOfferService(db)
        briefs = svc.get_briefs()
        assert len(briefs) == 2
        assert briefs[0].monetization_score == 90  # 내림차순

    def test_get_briefs_with_status_filter(self, db):
        src = _make_source(db)
        _make_premium_draft(db, src, premium_status="drafted")
        _make_premium_draft(db, src, premium_status="ready")
        _make_premium_draft(db, src, premium_status="drafted")
        svc = BriefOfferService(db)
        drafted = svc.get_briefs(status="drafted")
        assert len(drafted) == 2

    def test_get_briefs_empty(self, db):
        svc = BriefOfferService(db)
        assert svc.get_briefs() == []

    def test_get_brief_by_id(self, db):
        src = _make_source(db)
        draft = _make_premium_draft(db, src, hook="Find me")
        svc = BriefOfferService(db)
        result = svc.get_brief_by_id(draft.id)
        assert result is not None
        assert result.hook == "Find me"

    def test_get_brief_by_id_non_premium(self, db):
        src = _make_source(db)
        draft = Draft(
            source_item_id=src.id, hook="Not premium", body="body",
            category=ContentCategory.ECONOMY, risk_level=RiskLevel.LOW,
            approval_status=ApprovalStatus.PENDING,
            business_tags=json.dumps(["growth"]),
            created_at=datetime.now(timezone.utc),
        )
        db.add(draft)
        db.commit()
        db.refresh(draft)
        svc = BriefOfferService(db)
        assert svc.get_brief_by_id(draft.id) is None

    def test_get_brief_by_id_nonexistent(self, db):
        svc = BriefOfferService(db)
        assert svc.get_brief_by_id(9999) is None

    def test_count_by_status(self, db):
        src = _make_source(db)
        _make_premium_draft(db, src, premium_status="new")
        _make_premium_draft(db, src, premium_status="drafted")
        _make_premium_draft(db, src, premium_status="drafted")
        _make_premium_draft(db, src, premium_status="ready")
        svc = BriefOfferService(db)
        counts = svc.count_by_status()
        assert counts["new"] == 1
        assert counts["drafted"] == 2
        assert counts["ready"] == 1


# ─── 상태 변경 테스트 ────────────────────────────────────────

class TestSetStatus:
    def test_set_status_valid(self, db):
        src = _make_source(db)
        draft = _make_premium_draft(db, src, premium_status="new")
        svc = BriefOfferService(db)
        result = svc.set_status(draft.id, "drafted")
        assert result is not None
        assert result.premium_status == "drafted"
        assert result.premium_updated_at is not None

    def test_set_status_to_ready(self, db):
        src = _make_source(db)
        draft = _make_premium_draft(db, src, premium_status="drafted")
        svc = BriefOfferService(db)
        result = svc.set_status(draft.id, "ready")
        assert result.premium_status == "ready"

    def test_set_status_invalid(self, db):
        src = _make_source(db)
        draft = _make_premium_draft(db, src)
        svc = BriefOfferService(db)
        result = svc.set_status(draft.id, "invalid_status")
        assert result is None

    def test_set_status_nonexistent(self, db):
        svc = BriefOfferService(db)
        assert svc.set_status(9999, "drafted") is None


# ─── 브리프 유형 테스트 ──────────────────────────────────────

class TestSetBriefType:
    def test_set_brief_type(self, db):
        src = _make_source(db)
        draft = _make_premium_draft(db, src)
        svc = BriefOfferService(db)
        result = svc.set_brief_type(draft.id, "policy_brief")
        assert result is not None
        assert result.brief_type == "policy_brief"

    def test_set_brief_type_truncates(self, db):
        src = _make_source(db)
        draft = _make_premium_draft(db, src)
        svc = BriefOfferService(db)
        result = svc.set_brief_type(draft.id, "x" * 100)
        assert len(result.brief_type) == 50

    def test_set_brief_type_nonexistent(self, db):
        svc = BriefOfferService(db)
        assert svc.set_brief_type(9999, "policy_brief") is None


# ─── 대상 독자 테스트 ────────────────────────────────────────

class TestSetTargetReader:
    def test_set_target_reader(self, db):
        src = _make_source(db)
        draft = _make_premium_draft(db, src)
        svc = BriefOfferService(db)
        result = svc.set_target_reader(draft.id, "investors")
        assert result is not None
        assert result.target_reader_type == "investors"

    def test_set_target_reader_truncates(self, db):
        src = _make_source(db)
        draft = _make_premium_draft(db, src)
        svc = BriefOfferService(db)
        result = svc.set_target_reader(draft.id, "x" * 200)
        assert len(result.target_reader_type) == 100

    def test_set_target_reader_nonexistent(self, db):
        svc = BriefOfferService(db)
        assert svc.set_target_reader(9999, "investors") is None


# ─── 가격 티어 테스트 ────────────────────────────────────────

class TestSetPriceTier:
    def test_set_price_tier_low(self, db):
        src = _make_source(db)
        draft = _make_premium_draft(db, src)
        svc = BriefOfferService(db)
        result = svc.set_price_tier(draft.id, "low")
        assert result is not None
        assert result.brief_price_tier == "low"

    def test_set_price_tier_mid(self, db):
        src = _make_source(db)
        draft = _make_premium_draft(db, src)
        svc = BriefOfferService(db)
        result = svc.set_price_tier(draft.id, "mid")
        assert result.brief_price_tier == "mid"

    def test_set_price_tier_premium(self, db):
        src = _make_source(db)
        draft = _make_premium_draft(db, src)
        svc = BriefOfferService(db)
        result = svc.set_price_tier(draft.id, "premium")
        assert result.brief_price_tier == "premium"

    def test_set_price_tier_invalid(self, db):
        src = _make_source(db)
        draft = _make_premium_draft(db, src)
        svc = BriefOfferService(db)
        result = svc.set_price_tier(draft.id, "ultra")
        assert result is None

    def test_set_price_tier_nonexistent(self, db):
        svc = BriefOfferService(db)
        assert svc.set_price_tier(9999, "low") is None


# ─── 요약 메모 테스트 ────────────────────────────────────────

class TestSetSummaryNote:
    def test_set_summary_note(self, db):
        src = _make_source(db)
        draft = _make_premium_draft(db, src)
        svc = BriefOfferService(db)
        result = svc.set_summary_note(draft.id, "Weekly Korea labor brief for Q2")
        assert result is not None
        assert result.brief_summary_note == "Weekly Korea labor brief for Q2"

    def test_set_summary_note_truncates(self, db):
        src = _make_source(db)
        draft = _make_premium_draft(db, src)
        svc = BriefOfferService(db)
        result = svc.set_summary_note(draft.id, "A" * 600)
        assert len(result.brief_summary_note) == 500

    def test_set_summary_note_nonexistent(self, db):
        svc = BriefOfferService(db)
        assert svc.set_summary_note(9999, "note") is None


# ─── 내보내기 테스트 ──────────────────────────────────────────

class TestExportBriefs:
    def test_export_briefs_structure(self, db):
        src = _make_source(db, title="Export Source")
        _make_premium_draft(
            db, src, hook="Export Hook", score=75,
            premium_status="drafted", brief_type="policy_brief",
            brief_price_tier="mid", brief_summary_note="Test summary",
            target_reader="investors", premium_reason="High value topic",
        )
        svc = BriefOfferService(db)
        items = svc.export_briefs()
        assert len(items) == 1
        item = items[0]
        assert item["hook"] == "Export Hook"
        assert item["monetization_score"] == 75
        assert item["premium_status"] == "drafted"
        assert item["brief_type"] == "policy_brief"
        assert item["brief_price_tier"] == "mid"
        assert item["brief_summary_note"] == "Test summary"
        assert item["target_reader_type"] == "investors"
        assert item["premium_reason"] == "High value topic"
        assert item["source_title"] == "Export Source"
        assert "created_at" in item
        assert "business_tags" in item

    def test_export_briefs_with_status_filter(self, db):
        src = _make_source(db)
        _make_premium_draft(db, src, premium_status="ready")
        _make_premium_draft(db, src, premium_status="drafted")
        svc = BriefOfferService(db)
        items = svc.export_briefs(status="ready")
        assert len(items) == 1

    def test_export_briefs_empty(self, db):
        svc = BriefOfferService(db)
        assert svc.export_briefs() == []


# ─── 포맷 요약 테스트 ────────────────────────────────────────

class TestFormatSummary:
    def test_format_summary_empty(self, db):
        svc = BriefOfferService(db)
        text = svc.format_summary()
        assert "없음" in text

    def test_format_summary_with_data(self, db):
        src = _make_source(db)
        _make_premium_draft(db, src, premium_status="new")
        _make_premium_draft(db, src, premium_status="drafted")
        _make_premium_draft(
            db, src, premium_status="ready",
            brief_type="policy_brief", brief_price_tier="premium",
        )
        svc = BriefOfferService(db)
        text = svc.format_summary()
        assert "Premium Korea Brief" in text
        assert "3건" in text
        assert "신규" in text
        assert "초안작성" in text
        assert "발행준비" in text
        assert "policy_brief" in text
        assert "Premium" in text

    def test_format_summary_tier_distribution(self, db):
        src = _make_source(db)
        _make_premium_draft(db, src, brief_price_tier="low")
        _make_premium_draft(db, src, brief_price_tier="mid")
        _make_premium_draft(db, src, brief_price_tier="premium")
        svc = BriefOfferService(db)
        text = svc.format_summary()
        assert "Low" in text
        assert "Mid" in text
        assert "Premium" in text


# ─── 포맷 상세 테스트 ────────────────────────────────────────

class TestFormatBriefDetail:
    def test_format_detail_full(self, db):
        src = _make_source(db, title="Detail Source")
        draft = _make_premium_draft(
            db, src, hook="Korea labor market shift",
            premium_status="drafted", brief_type="market_brief",
            brief_price_tier="premium", brief_summary_note="Investor brief Q2",
            target_reader="investors", score=85,
            premium_reason="High growth topic", premium_note="Operator says go",
            b2b=True,
        )
        svc = BriefOfferService(db)
        text = svc.format_brief_detail(draft)
        assert str(draft.id) in text
        assert "Korea labor market shift" in text
        assert "초안작성" in text
        assert "market_brief" in text
        assert "investors" in text
        assert "Premium" in text
        assert "85" in text
        assert "Investor brief Q2" in text
        assert "High growth topic" in text
        assert "Operator says go" in text
        assert "B2B" in text
        assert "Detail Source" in text

    def test_format_detail_minimal(self, db):
        src = _make_source(db)
        draft = _make_premium_draft(db, src, hook="Minimal brief")
        svc = BriefOfferService(db)
        text = svc.format_brief_detail(draft)
        assert "Brief #" in text
        assert "Minimal brief" in text
        # 미설정 필드는 표시 안됨
        assert "유형" not in text
        assert "티어" not in text
