"""
뉴스레터/리드자석 운영 루틴 서비스 테스트
==========================================
NewsletterRoutineService 조회, 카운트, 내보내기, 포맷 검증.
"""

import pytest
from datetime import datetime, timezone
from app.models.content import (
    Base, Draft, SourceItem, ContentCategory, RiskLevel, ApprovalStatus,
)
from app.services.newsletter_routine_service import (
    NewsletterRoutineService,
    NEWSLETTER_BUCKETS,
)


@pytest.fixture
def db(db_session):
    return db_session


def _make_source(db, title="Newsletter Test Source"):
    src = SourceItem(
        title=title, source_text="test text", source_type="manual",
        language="ko", created_at=datetime.now(timezone.utc),
    )
    db.add(src)
    db.commit()
    db.refresh(src)
    return src


def _make_draft(
    db, source, hook="Test Hook",
    cta_type=None, asset_goal=None,
    email_bucket=None, email_goal=None,
    lead_asset_name=None, lead_asset_type=None, lead_asset_note=None,
    score=None,
):
    draft = Draft(
        source_item_id=source.id,
        hook=hook,
        body="Test body about Korea newsletter content",
        category=ContentCategory.SOCIETY,
        risk_level=RiskLevel.LOW,
        approval_status=ApprovalStatus.PUBLISHED,
        cta_type=cta_type,
        asset_goal=asset_goal,
        email_bucket=email_bucket,
        email_goal=email_goal,
        lead_asset_name=lead_asset_name,
        lead_asset_type=lead_asset_type,
        lead_asset_note=lead_asset_note,
        monetization_score=score,
        created_at=datetime.now(timezone.utc),
    )
    db.add(draft)
    db.commit()
    db.refresh(draft)
    return draft


# ─── 상수 테스트 ──────────────────────────────────────────────

class TestConstants:
    def test_newsletter_buckets(self):
        assert NEWSLETTER_BUCKETS == ("weekly_free", "onboarding", "lead_nurture", "premium_teaser")


# ─── 버킷별 조회 ─────────────────────────────────────────────

class TestGetByBucket:
    def test_weekly_free(self, db):
        src = _make_source(db)
        _make_draft(db, src, hook="Weekly 1", email_bucket="weekly_free")
        _make_draft(db, src, hook="Weekly 2", email_bucket="weekly_free")
        _make_draft(db, src, hook="Other", email_bucket="b2b_nurture")
        svc = NewsletterRoutineService(db)
        result = svc.get_weekly_free()
        assert len(result) == 2

    def test_onboarding(self, db):
        src = _make_source(db)
        _make_draft(db, src, email_bucket="onboarding")
        svc = NewsletterRoutineService(db)
        assert len(svc.get_onboarding()) == 1

    def test_lead_nurture(self, db):
        src = _make_source(db)
        _make_draft(db, src, email_bucket="lead_nurture")
        svc = NewsletterRoutineService(db)
        assert len(svc.get_lead_nurture()) == 1

    def test_premium_teaser(self, db):
        src = _make_source(db)
        _make_draft(db, src, email_bucket="premium_teaser")
        svc = NewsletterRoutineService(db)
        assert len(svc.get_premium_teaser()) == 1

    def test_get_by_bucket_empty(self, db):
        svc = NewsletterRoutineService(db)
        assert svc.get_by_bucket("weekly_free") == []

    def test_get_by_bucket_respects_limit(self, db):
        src = _make_source(db)
        for i in range(5):
            _make_draft(db, src, hook=f"W{i}", email_bucket="weekly_free")
        svc = NewsletterRoutineService(db)
        assert len(svc.get_by_bucket("weekly_free", limit=3)) == 3


# ─── 전체 뉴스레터 후보 ──────────────────────────────────────

class TestGetAllNewsletter:
    def test_combines_sources(self, db):
        src = _make_source(db)
        _make_draft(db, src, hook="CTA signup", cta_type="newsletter_signup")
        _make_draft(db, src, hook="Asset push", asset_goal="newsletter_push")
        _make_draft(db, src, hook="Bucket weekly", email_bucket="weekly_free")
        _make_draft(db, src, hook="Unrelated", cta_type="follow")
        svc = NewsletterRoutineService(db)
        result = svc.get_all_newsletter_candidates()
        assert len(result) == 3

    def test_empty(self, db):
        svc = NewsletterRoutineService(db)
        assert svc.get_all_newsletter_candidates() == []


# ─── 리드자석 후보 ───────────────────────────────────────────

class TestGetLeadMagnet:
    def test_by_asset_name(self, db):
        src = _make_source(db)
        _make_draft(db, src, hook="Has asset", lead_asset_name="Korea Checklist")
        svc = NewsletterRoutineService(db)
        assert len(svc.get_lead_magnet_candidates()) == 1

    def test_by_cta(self, db):
        src = _make_source(db)
        _make_draft(db, src, hook="CTA lead", cta_type="lead_magnet")
        svc = NewsletterRoutineService(db)
        assert len(svc.get_lead_magnet_candidates()) == 1

    def test_by_asset_goal(self, db):
        src = _make_source(db)
        _make_draft(db, src, hook="Goal push", asset_goal="lead_magnet_push")
        svc = NewsletterRoutineService(db)
        assert len(svc.get_lead_magnet_candidates()) == 1

    def test_empty(self, db):
        svc = NewsletterRoutineService(db)
        assert svc.get_lead_magnet_candidates() == []


# ─── 카운트 ──────────────────────────────────────────────────

class TestCounts:
    def test_count_by_bucket(self, db):
        src = _make_source(db)
        _make_draft(db, src, email_bucket="weekly_free")
        _make_draft(db, src, email_bucket="weekly_free")
        _make_draft(db, src, email_bucket="onboarding")
        _make_draft(db, src, email_bucket="b2b_nurture")  # not in NEWSLETTER_BUCKETS
        svc = NewsletterRoutineService(db)
        counts = svc.count_by_bucket()
        assert counts["weekly_free"] == 2
        assert counts["onboarding"] == 1
        assert "b2b_nurture" not in counts

    def test_count_lead_assets(self, db):
        src = _make_source(db)
        _make_draft(db, src, lead_asset_type="pdf")
        _make_draft(db, src, lead_asset_type="pdf")
        _make_draft(db, src, lead_asset_type="checklist")
        svc = NewsletterRoutineService(db)
        counts = svc.count_lead_assets()
        assert counts["pdf"] == 2
        assert counts["checklist"] == 1

    def test_count_empty(self, db):
        svc = NewsletterRoutineService(db)
        assert svc.count_by_bucket() == {}
        assert svc.count_lead_assets() == {}


# ─── 내보내기 ────────────────────────────────────────────────

class TestExport:
    def test_export_newsletter_structure(self, db):
        src = _make_source(db, title="NL Source")
        _make_draft(
            db, src, hook="Export test", email_bucket="weekly_free",
            email_goal="signup", cta_type="newsletter_signup",
            lead_asset_name="Korea Brief", score=60,
        )
        svc = NewsletterRoutineService(db)
        items = svc.export_newsletter()
        assert len(items) == 1
        item = items[0]
        assert item["hook"] == "Export test"
        assert item["email_bucket"] == "weekly_free"
        assert item["email_goal"] == "signup"
        assert item["cta_type"] == "newsletter_signup"
        assert item["lead_asset_name"] == "Korea Brief"
        assert item["monetization_score"] == 60
        assert item["source_title"] == "NL Source"
        assert "created_at" in item

    def test_export_newsletter_with_bucket_filter(self, db):
        src = _make_source(db)
        _make_draft(db, src, email_bucket="weekly_free")
        _make_draft(db, src, email_bucket="onboarding")
        svc = NewsletterRoutineService(db)
        items = svc.export_newsletter(bucket="weekly_free")
        assert len(items) == 1

    def test_export_lead_magnets(self, db):
        src = _make_source(db, title="Lead Source")
        _make_draft(
            db, src, hook="Lead export", cta_type="lead_magnet",
            lead_asset_name="Checklist", lead_asset_type="checklist",
            lead_asset_note="Ready to ship",
        )
        svc = NewsletterRoutineService(db)
        items = svc.export_lead_magnets()
        assert len(items) == 1
        item = items[0]
        assert item["lead_asset_name"] == "Checklist"
        assert item["lead_asset_type"] == "checklist"
        assert item["lead_asset_note"] == "Ready to ship"

    def test_export_empty(self, db):
        svc = NewsletterRoutineService(db)
        assert svc.export_newsletter() == []
        assert svc.export_lead_magnets() == []


# ─── 포맷 요약 ───────────────────────────────────────────────

class TestFormatSummary:
    def test_empty(self, db):
        svc = NewsletterRoutineService(db)
        text = svc.format_newsletter_summary()
        assert "없음" in text

    def test_with_data(self, db):
        src = _make_source(db)
        _make_draft(db, src, email_bucket="weekly_free")
        _make_draft(db, src, email_bucket="onboarding")
        _make_draft(db, src, lead_asset_type="pdf")
        svc = NewsletterRoutineService(db)
        text = svc.format_newsletter_summary()
        assert "뉴스레터 운영 현황" in text
        assert "Weekly Free" in text
        assert "Onboarding" in text
        assert "pdf" in text

    def test_recent_preview(self, db):
        src = _make_source(db)
        _make_draft(db, src, hook="Preview item", email_bucket="weekly_free", email_goal="signup")
        svc = NewsletterRoutineService(db)
        text = svc.format_newsletter_summary()
        assert "최근 후보" in text
        assert "Preview item" in text


# ─── 포맷 상세 ───────────────────────────────────────────────

class TestFormatDetail:
    def test_newsletter_detail(self, db):
        src = _make_source(db, title="Detail Source")
        draft = _make_draft(
            db, src, hook="Detail test",
            email_bucket="weekly_free", email_goal="signup",
            cta_type="newsletter_signup", score=70,
            lead_asset_name="Korea Guide", lead_asset_type="pdf",
            lead_asset_note="First draft done",
        )
        svc = NewsletterRoutineService(db)
        text = svc.format_newsletter_detail(draft)
        assert str(draft.id) in text
        assert "Detail test" in text
        assert "weekly_free" in text
        assert "signup" in text
        assert "newsletter_signup" in text
        assert "Korea Guide" in text
        assert "pdf" in text
        assert "First draft done" in text
        assert "Detail Source" in text

    def test_newsletter_detail_minimal(self, db):
        src = _make_source(db)
        draft = _make_draft(db, src, hook="Minimal")
        svc = NewsletterRoutineService(db)
        text = svc.format_newsletter_detail(draft)
        assert "Minimal" in text

    def test_lead_detail(self, db):
        src = _make_source(db, title="Lead Source")
        draft = _make_draft(
            db, src, hook="Lead detail",
            lead_asset_name="Korea Checklist",
            lead_asset_type="checklist",
            lead_asset_note="Needs review",
            cta_type="lead_magnet",
            email_bucket="lead_nurture",
        )
        svc = NewsletterRoutineService(db)
        text = svc.format_lead_detail(draft)
        assert "리드자석" in text
        assert "Korea Checklist" in text
        assert "checklist" in text
        assert "Needs review" in text
        assert "lead_magnet" in text
        assert "lead_nurture" in text

    def test_lead_detail_empty_assets(self, db):
        src = _make_source(db)
        draft = _make_draft(db, src, hook="No asset")
        svc = NewsletterRoutineService(db)
        text = svc.format_lead_detail(draft)
        assert "미설정" in text


# ─── get_draft_by_id ─────────────────────────────────────────

class TestGetDraftById:
    def test_found(self, db):
        src = _make_source(db)
        draft = _make_draft(db, src, hook="Find me")
        svc = NewsletterRoutineService(db)
        result = svc.get_draft_by_id(draft.id)
        assert result is not None
        assert result.hook == "Find me"

    def test_not_found(self, db):
        svc = NewsletterRoutineService(db)
        assert svc.get_draft_by_id(9999) is None
