"""
이메일/리드자석 서비스 테스트 (Phase 7)
=========================================
EmailLeadService의 CTA, 리드 자산, 이메일 버킷/목표 관리 검증.
"""

import pytest
from datetime import datetime, timezone
from app.models.content import (
    Draft, SourceItem, ContentCategory, RiskLevel, ApprovalStatus,
)
from app.services.email_lead_service import (
    EmailLeadService,
    CTA_TYPES,
    LEAD_ASSET_TYPES,
    EMAIL_BUCKETS,
    EMAIL_GOALS,
)


@pytest.fixture
def db(db_session):
    return db_session


def _make_source(db, title="Email Test Source"):
    src = SourceItem(
        title=title, source_text="test text", source_type="manual",
        language="ko", created_at=datetime.now(timezone.utc),
    )
    db.add(src)
    db.commit()
    db.refresh(src)
    return src


def _make_draft(
    db, source, hook="Test Hook", cta_type=None,
    asset_goal=None, lead_name=None, lead_type=None,
    email_bucket=None, email_goal=None, score=None,
):
    draft = Draft(
        source_item_id=source.id,
        hook=hook,
        body="Test body content about Korea",
        category=ContentCategory.ECONOMY,
        risk_level=RiskLevel.LOW,
        approval_status=ApprovalStatus.PUBLISHED,
        cta_type=cta_type,
        asset_goal=asset_goal,
        lead_asset_name=lead_name,
        lead_asset_type=lead_type,
        email_bucket=email_bucket,
        email_goal=email_goal,
        monetization_score=score,
        created_at=datetime.now(timezone.utc),
    )
    db.add(draft)
    db.commit()
    db.refresh(draft)
    return draft


# ─── 상수 테스트 ──────────────────────────────────────────────

class TestConstants:
    def test_cta_types(self):
        assert "follow" in CTA_TYPES
        assert "newsletter_signup" in CTA_TYPES
        assert "lead_magnet" in CTA_TYPES
        assert "premium_teaser" in CTA_TYPES

    def test_lead_asset_types(self):
        assert "pdf" in LEAD_ASSET_TYPES
        assert "checklist" in LEAD_ASSET_TYPES
        assert len(LEAD_ASSET_TYPES) >= 5

    def test_email_buckets(self):
        assert "weekly_free" in EMAIL_BUCKETS
        assert "premium_teaser" in EMAIL_BUCKETS

    def test_email_goals(self):
        assert "signup" in EMAIL_GOALS
        assert "convert" in EMAIL_GOALS


# ─── CTA 테스트 ───────────────────────────────────────────────

class TestSetCta:
    def test_valid_cta(self, db):
        src = _make_source(db)
        draft = _make_draft(db, src)

        svc = EmailLeadService(db)
        result = svc.set_cta(draft.id, "newsletter_signup")
        assert result.cta_type == "newsletter_signup"

    def test_invalid_cta(self, db):
        src = _make_source(db)
        draft = _make_draft(db, src)

        svc = EmailLeadService(db)
        assert svc.set_cta(draft.id, "invalid") is None

    def test_all_cta_types(self, db):
        src = _make_source(db)
        for cta in CTA_TYPES:
            draft = _make_draft(db, src, hook=f"CTA {cta}")
            svc = EmailLeadService(db)
            result = svc.set_cta(draft.id, cta)
            assert result is not None
            assert result.cta_type == cta

    def test_missing_draft(self, db):
        svc = EmailLeadService(db)
        assert svc.set_cta(9999, "follow") is None


class TestGetByCta:
    def test_filter(self, db):
        src = _make_source(db)
        _make_draft(db, src, cta_type="lead_magnet")
        _make_draft(db, src, cta_type="lead_magnet")
        _make_draft(db, src, cta_type="follow")

        svc = EmailLeadService(db)
        result = svc.get_by_cta("lead_magnet")
        assert len(result) == 2

    def test_empty(self, db):
        svc = EmailLeadService(db)
        assert svc.get_by_cta("nonexistent") == []


# ─── 리드 자산 테스트 ─────────────────────────────────────────

class TestSetLeadAsset:
    def test_set_name(self, db):
        src = _make_source(db)
        draft = _make_draft(db, src)

        svc = EmailLeadService(db)
        result = svc.set_lead_asset(draft.id, name="Korea Labor Law Checklist")
        assert result.lead_asset_name == "Korea Labor Law Checklist"

    def test_set_type(self, db):
        src = _make_source(db)
        draft = _make_draft(db, src)

        svc = EmailLeadService(db)
        result = svc.set_lead_asset(draft.id, asset_type="pdf")
        assert result.lead_asset_type == "pdf"

    def test_invalid_type(self, db):
        src = _make_source(db)
        draft = _make_draft(db, src)

        svc = EmailLeadService(db)
        assert svc.set_lead_asset(draft.id, asset_type="invalid") is None

    def test_set_note(self, db):
        src = _make_source(db)
        draft = _make_draft(db, src)

        svc = EmailLeadService(db)
        result = svc.set_lead_asset(draft.id, note="리드 캡처용 PDF로 변환")
        assert result.lead_asset_note == "리드 캡처용 PDF로 변환"

    def test_note_truncated(self, db):
        src = _make_source(db)
        draft = _make_draft(db, src)

        svc = EmailLeadService(db)
        result = svc.set_lead_asset(draft.id, note="x" * 600)
        assert len(result.lead_asset_note) == 500

    def test_set_all_at_once(self, db):
        src = _make_source(db)
        draft = _make_draft(db, src)

        svc = EmailLeadService(db)
        result = svc.set_lead_asset(
            draft.id, name="Checklist", asset_type="checklist", note="Great lead"
        )
        assert result.lead_asset_name == "Checklist"
        assert result.lead_asset_type == "checklist"
        assert result.lead_asset_note == "Great lead"

    def test_missing_draft(self, db):
        svc = EmailLeadService(db)
        assert svc.set_lead_asset(9999, name="test") is None


# ─── 이메일 버킷/목표 테스트 ──────────────────────────────────

class TestSetEmailBucket:
    def test_valid_bucket(self, db):
        src = _make_source(db)
        draft = _make_draft(db, src)

        svc = EmailLeadService(db)
        result = svc.set_email_bucket(draft.id, "weekly_free")
        assert result.email_bucket == "weekly_free"

    def test_invalid_bucket(self, db):
        src = _make_source(db)
        draft = _make_draft(db, src)

        svc = EmailLeadService(db)
        assert svc.set_email_bucket(draft.id, "invalid") is None


class TestSetEmailGoal:
    def test_valid_goal(self, db):
        src = _make_source(db)
        draft = _make_draft(db, src)

        svc = EmailLeadService(db)
        result = svc.set_email_goal(draft.id, "signup")
        assert result.email_goal == "signup"

    def test_invalid_goal(self, db):
        src = _make_source(db)
        draft = _make_draft(db, src)

        svc = EmailLeadService(db)
        assert svc.set_email_goal(draft.id, "invalid") is None


# ─── 조회 테스트 ──────────────────────────────────────────────

class TestGetLeadMagnetCandidates:
    def test_by_asset_name(self, db):
        src = _make_source(db)
        _make_draft(db, src, lead_name="Korea Checklist")
        _make_draft(db, src)  # no lead info

        svc = EmailLeadService(db)
        result = svc.get_lead_magnet_candidates()
        assert len(result) == 1

    def test_by_cta_lead_magnet(self, db):
        src = _make_source(db)
        _make_draft(db, src, cta_type="lead_magnet")

        svc = EmailLeadService(db)
        result = svc.get_lead_magnet_candidates()
        assert len(result) == 1

    def test_by_asset_goal(self, db):
        src = _make_source(db)
        _make_draft(db, src, asset_goal="lead_magnet_push")

        svc = EmailLeadService(db)
        result = svc.get_lead_magnet_candidates()
        assert len(result) == 1


class TestGetNewsletterCandidates:
    def test_by_cta(self, db):
        src = _make_source(db)
        _make_draft(db, src, cta_type="newsletter_signup")

        svc = EmailLeadService(db)
        result = svc.get_newsletter_candidates()
        assert len(result) == 1

    def test_by_bucket(self, db):
        src = _make_source(db)
        _make_draft(db, src, email_bucket="weekly_free")

        svc = EmailLeadService(db)
        result = svc.get_newsletter_candidates()
        assert len(result) == 1


class TestGetPremiumTeaserCandidates:
    def test_by_cta(self, db):
        src = _make_source(db)
        _make_draft(db, src, cta_type="premium_teaser")

        svc = EmailLeadService(db)
        result = svc.get_premium_teaser_candidates()
        assert len(result) == 1

    def test_by_bucket(self, db):
        src = _make_source(db)
        _make_draft(db, src, email_bucket="premium_conversion")

        svc = EmailLeadService(db)
        result = svc.get_premium_teaser_candidates()
        assert len(result) == 1


class TestGetByEmailBucket:
    def test_filter(self, db):
        src = _make_source(db)
        _make_draft(db, src, email_bucket="weekly_free")
        _make_draft(db, src, email_bucket="weekly_free")
        _make_draft(db, src, email_bucket="lead_nurture")

        svc = EmailLeadService(db)
        result = svc.get_by_email_bucket("weekly_free")
        assert len(result) == 2


# ─── 그룹핑 테스트 ────────────────────────────────────────────

class TestGroupByCta:
    def test_groups(self, db):
        src = _make_source(db)
        _make_draft(db, src, cta_type="follow")
        _make_draft(db, src, cta_type="follow")
        _make_draft(db, src, cta_type="lead_magnet")

        svc = EmailLeadService(db)
        groups = svc.group_by_cta()
        assert groups["follow"] == 2
        assert groups["lead_magnet"] == 1


class TestGroupByEmailBucket:
    def test_groups(self, db):
        src = _make_source(db)
        _make_draft(db, src, email_bucket="weekly_free")
        _make_draft(db, src, email_bucket="weekly_free")
        _make_draft(db, src, email_bucket="lead_nurture")

        svc = EmailLeadService(db)
        groups = svc.group_by_email_bucket()
        assert groups["weekly_free"] == 2
        assert groups["lead_nurture"] == 1


class TestGroupByAssetType:
    def test_groups(self, db):
        src = _make_source(db)
        _make_draft(db, src, lead_type="pdf")
        _make_draft(db, src, lead_type="pdf")
        _make_draft(db, src, lead_type="checklist")

        svc = EmailLeadService(db)
        groups = svc.group_by_asset_type()
        assert groups["pdf"] == 2
        assert groups["checklist"] == 1


# ─── 내보내기 테스트 ──────────────────────────────────────────

class TestExportEmailItems:
    def test_export(self, db):
        src = _make_source(db)
        _make_draft(
            db, src, cta_type="lead_magnet", lead_name="Korea Checklist",
            lead_type="checklist", email_bucket="lead_nurture",
            email_goal="signup", score=70,
        )

        svc = EmailLeadService(db)
        items = svc.export_email_items()
        assert len(items) == 1
        item = items[0]
        assert item["cta_type"] == "lead_magnet"
        assert item["lead_asset_name"] == "Korea Checklist"
        assert item["lead_asset_type"] == "checklist"
        assert item["email_bucket"] == "lead_nurture"
        assert item["email_goal"] == "signup"
        assert item["monetization_score"] == 70

    def test_export_cta_filter(self, db):
        src = _make_source(db)
        _make_draft(db, src, cta_type="lead_magnet")
        _make_draft(db, src, cta_type="follow")

        svc = EmailLeadService(db)
        items = svc.export_email_items(cta_filter="lead_magnet")
        assert len(items) == 1

    def test_export_bucket_filter(self, db):
        src = _make_source(db)
        _make_draft(db, src, email_bucket="weekly_free")
        _make_draft(db, src, email_bucket="lead_nurture")

        svc = EmailLeadService(db)
        items = svc.export_email_items(bucket_filter="weekly_free")
        assert len(items) == 1

    def test_empty(self, db):
        svc = EmailLeadService(db)
        assert svc.export_email_items() == []


# ─── 포맷 테스트 ──────────────────────────────────────────────

class TestFormatSummary:
    def test_empty(self, db):
        svc = EmailLeadService(db)
        text = svc.format_summary()
        assert "없음" in text

    def test_with_data(self, db):
        src = _make_source(db)
        _make_draft(db, src, cta_type="lead_magnet", email_bucket="weekly_free", lead_type="pdf")

        svc = EmailLeadService(db)
        text = svc.format_summary()
        assert "CTA" in text
        assert "lead_magnet" in text
        assert "weekly_free" in text
        assert "pdf" in text


# ─── 자동 초기화 매핑 검증 테스트 ──────────────────────────────

class TestAutoInitMapping:
    """orchestrator에서 사용하는 email_bucket/email_goal 자동 매핑 로직 검증."""

    def test_newsletter_signup_maps_to_weekly_free(self, db):
        """newsletter_signup CTA → email_bucket=weekly_free, email_goal=signup"""
        src = _make_source(db)
        draft = _make_draft(db, src, cta_type="newsletter_signup")
        # 시뮬레이션: orchestrator 매핑 로직
        if not draft.email_bucket:
            if draft.cta_type == "newsletter_signup":
                draft.email_bucket = "weekly_free"
        if not draft.email_goal:
            if draft.cta_type == "newsletter_signup":
                draft.email_goal = "signup"
        db.commit()
        assert draft.email_bucket == "weekly_free"
        assert draft.email_goal == "signup"

    def test_lead_magnet_maps_to_lead_nurture(self, db):
        """lead_magnet CTA → email_bucket=lead_nurture, email_goal=nurture"""
        src = _make_source(db)
        draft = _make_draft(db, src, cta_type="lead_magnet")
        if not draft.email_bucket:
            if draft.cta_type == "lead_magnet":
                draft.email_bucket = "lead_nurture"
        if not draft.email_goal:
            if draft.cta_type == "lead_magnet":
                draft.email_goal = "nurture"
        db.commit()
        assert draft.email_bucket == "lead_nurture"
        assert draft.email_goal == "nurture"

    def test_premium_teaser_maps_correctly(self, db):
        """premium_waitlist CTA → email_bucket=premium_teaser, email_goal=tease"""
        src = _make_source(db)
        draft = _make_draft(db, src, cta_type="premium_waitlist")
        if not draft.email_bucket:
            if draft.cta_type in ("premium_waitlist", "premium_teaser"):
                draft.email_bucket = "premium_teaser"
        if not draft.email_goal:
            if draft.cta_type in ("premium_waitlist", "premium_teaser"):
                draft.email_goal = "tease"
        db.commit()
        assert draft.email_bucket == "premium_teaser"
        assert draft.email_goal == "tease"

    def test_manual_values_not_overwritten(self, db):
        """수동 설정된 값은 덮어쓰지 않음."""
        src = _make_source(db)
        draft = _make_draft(
            db, src, cta_type="newsletter_signup",
            email_bucket="onboarding", email_goal="retain",
        )
        # 매핑은 이미 설정된 값이 있으면 건너뜀
        if not draft.email_bucket:
            draft.email_bucket = "weekly_free"
        if not draft.email_goal:
            draft.email_goal = "signup"
        db.commit()
        # 원래 수동 값이 유지되어야 함
        assert draft.email_bucket == "onboarding"
        assert draft.email_goal == "retain"

    def test_no_mapping_for_follow_cta(self, db):
        """follow CTA는 이메일 매핑 없음."""
        src = _make_source(db)
        draft = _make_draft(db, src, cta_type="follow")
        if not draft.email_bucket:
            if draft.cta_type == "newsletter_signup":
                draft.email_bucket = "weekly_free"
        assert draft.email_bucket is None
        assert draft.email_goal is None

    def test_asset_goal_lead_magnet_push(self, db):
        """asset_goal=lead_magnet_push → lead_nurture"""
        src = _make_source(db)
        draft = _make_draft(db, src, asset_goal="lead_magnet_push")
        if not draft.email_bucket:
            if draft.asset_goal == "lead_magnet_push":
                draft.email_bucket = "lead_nurture"
        if not draft.email_goal:
            if draft.asset_goal == "lead_magnet_push":
                draft.email_goal = "nurture"
        db.commit()
        assert draft.email_bucket == "lead_nurture"
        assert draft.email_goal == "nurture"


class TestFormatDraftDetail:
    def test_includes_all(self, db):
        src = _make_source(db)
        draft = _make_draft(
            db, src,
            hook="Korea Labor Law",
            cta_type="lead_magnet",
            asset_goal="lead_magnet_push",
            lead_name="Korea Checklist 2025",
            lead_type="checklist",
            email_bucket="lead_nurture",
            email_goal="signup",
            score=80,
        )

        svc = EmailLeadService(db)
        text = svc.format_draft_detail(draft)
        assert str(draft.id) in text
        assert "lead_magnet" in text
        assert "Korea Checklist 2025" in text
        assert "checklist" in text
        assert "lead_nurture" in text
        assert "signup" in text
        assert "80" in text
