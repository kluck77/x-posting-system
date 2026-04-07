"""
주간 운영 리포트 서비스 테스트
================================
WeeklyReportService 집계, 포맷, 내보내기 검증.
"""

import json
import pytest
from datetime import datetime, timezone, timedelta
from app.models.content import (
    Base, Draft, SourceItem, CtaCopy,
    ContentCategory, RiskLevel, ApprovalStatus,
)
from app.services.weekly_report_service import WeeklyReportService


@pytest.fixture
def db(db_session):
    return db_session


def _make_source(db, title="Weekly Test Source"):
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
    category=ContentCategory.ECONOMY,
    approval_status=ApprovalStatus.PUBLISHED,
    business_tags=None, cta_type=None, asset_goal=None,
    email_bucket=None, email_goal=None,
    lead_asset_name=None, lead_asset_type=None,
    monetization_score=None,
    premium_status=None, b2b_candidate=False, b2b_status=None,
    brief_type=None, brief_price_tier=None,
    created_days_ago=0,
):
    created = datetime.now(timezone.utc) - timedelta(days=created_days_ago)
    draft = Draft(
        source_item_id=source.id,
        hook=hook,
        body="Test body for weekly report",
        category=category,
        risk_level=RiskLevel.LOW,
        approval_status=approval_status,
        business_tags=json.dumps(business_tags) if business_tags else None,
        cta_type=cta_type,
        asset_goal=asset_goal,
        email_bucket=email_bucket,
        email_goal=email_goal,
        lead_asset_name=lead_asset_name,
        lead_asset_type=lead_asset_type,
        monetization_score=monetization_score,
        premium_status=premium_status,
        b2b_candidate=b2b_candidate,
        b2b_status=b2b_status,
        brief_type=brief_type,
        brief_price_tier=brief_price_tier,
        created_at=created,
    )
    db.add(draft)
    db.commit()
    db.refresh(draft)
    return draft


# ─── 리포트 생성 구조 ────────────────────────────────────────

class TestGenerateReport:
    def test_report_has_all_sections(self, db):
        svc = WeeklyReportService(db)
        report = svc.generate_report()
        assert "period_days" in report
        assert report["period_days"] == 7
        assert "generated_at" in report
        assert "content_summary" in report
        assert "newsletter_summary" in report
        assert "premium_summary" in report
        assert "brief_summary" in report
        assert "b2b_summary" in report
        assert "highlights" in report
        assert "followup_items" in report

    def test_custom_period(self, db):
        svc = WeeklyReportService(db)
        report = svc.generate_report(days=14)
        assert report["period_days"] == 14

    def test_empty_report(self, db):
        svc = WeeklyReportService(db)
        report = svc.generate_report()
        cs = report["content_summary"]
        assert cs["total_drafts"] == 0
        assert cs["published"] == 0


# ─── 콘텐츠 요약 ─────────────────────────────────────────────

class TestContentSummary:
    def test_counts_recent_drafts(self, db):
        src = _make_source(db)
        _make_draft(db, src, hook="Recent 1", created_days_ago=2)
        _make_draft(db, src, hook="Recent 2", created_days_ago=3,
                    approval_status=ApprovalStatus.REJECTED)
        _make_draft(db, src, hook="Old", created_days_ago=10)
        svc = WeeklyReportService(db)
        report = svc.generate_report(days=7)
        cs = report["content_summary"]
        assert cs["total_drafts"] == 2  # old one excluded
        assert cs["published"] == 1
        assert cs["rejected"] == 1

    def test_category_distribution(self, db):
        src = _make_source(db)
        _make_draft(db, src, category=ContentCategory.ECONOMY)
        _make_draft(db, src, category=ContentCategory.ECONOMY)
        _make_draft(db, src, category=ContentCategory.POLITICS)
        svc = WeeklyReportService(db)
        cs = svc.generate_report()["content_summary"]
        assert cs["category_distribution"]["economy"] == 2
        assert cs["category_distribution"]["politics"] == 1

    def test_business_tag_distribution(self, db):
        src = _make_source(db)
        _make_draft(db, src, business_tags=["growth", "newsletter"])
        _make_draft(db, src, business_tags=["growth", "premium_candidate"])
        svc = WeeklyReportService(db)
        cs = svc.generate_report()["content_summary"]
        assert cs["business_tag_distribution"]["growth"] == 2
        assert cs["business_tag_distribution"]["newsletter"] == 1

    def test_cta_distribution(self, db):
        src = _make_source(db)
        _make_draft(db, src, cta_type="follow")
        _make_draft(db, src, cta_type="follow")
        _make_draft(db, src, cta_type="newsletter_signup")
        svc = WeeklyReportService(db)
        cs = svc.generate_report()["content_summary"]
        assert cs["cta_distribution"]["follow"] == 2
        assert cs["cta_distribution"]["newsletter_signup"] == 1

    def test_pending_count(self, db):
        src = _make_source(db)
        _make_draft(db, src, approval_status=ApprovalStatus.PENDING)
        _make_draft(db, src, approval_status=ApprovalStatus.PENDING)
        svc = WeeklyReportService(db)
        cs = svc.generate_report()["content_summary"]
        assert cs["pending"] == 2


# ─── 뉴스레터 요약 ───────────────────────────────────────────

class TestNewsletterSummary:
    def test_counts(self, db):
        src = _make_source(db)
        _make_draft(db, src, email_bucket="weekly_free")
        _make_draft(db, src, email_bucket="weekly_free")
        _make_draft(db, src, lead_asset_type="pdf")
        svc = WeeklyReportService(db)
        ns = svc.generate_report()["newsletter_summary"]
        assert ns["total_newsletter"] >= 2
        assert ns["total_lead_assets"] >= 1

    def test_recent_counts(self, db):
        src = _make_source(db)
        _make_draft(db, src, cta_type="newsletter_signup", created_days_ago=2)
        _make_draft(db, src, cta_type="newsletter_signup", created_days_ago=10)
        svc = WeeklyReportService(db)
        ns = svc.generate_report(days=7)["newsletter_summary"]
        assert ns["recent_newsletter_candidates"] == 1


# ─── 프리미엄 요약 ───────────────────────────────────────────

class TestPremiumSummary:
    def test_counts(self, db):
        src = _make_source(db)
        _make_draft(db, src, business_tags=["premium_candidate"],
                    premium_status="new", monetization_score=80)
        _make_draft(db, src, business_tags=["premium_candidate"],
                    premium_status="shortlisted", monetization_score=90)
        svc = WeeklyReportService(db)
        ps = svc.generate_report()["premium_summary"]
        assert ps["total"] == 2
        assert ps["status_distribution"]["new"] == 1
        assert ps["status_distribution"]["shortlisted"] == 1
        assert len(ps["top_candidates"]) == 2
        # 높은 점수 먼저
        assert ps["top_candidates"][0]["monetization_score"] == 90


# ─── 브리프 요약 ─────────────────────────────────────────────

class TestBriefSummary:
    def test_counts(self, db):
        src = _make_source(db)
        _make_draft(db, src, business_tags=["premium_candidate"],
                    premium_status="drafted", brief_type="policy_brief",
                    brief_price_tier="premium")
        svc = WeeklyReportService(db)
        brs = svc.generate_report()["brief_summary"]
        assert brs["total"] >= 1
        assert "drafted" in brs["status_distribution"]


# ─── B2B 요약 ────────────────────────────────────────────────

class TestB2BSummary:
    def test_counts(self, db):
        src = _make_source(db)
        _make_draft(db, src, b2b_candidate=True, b2b_status="new")
        _make_draft(db, src, b2b_candidate=True, b2b_status="reviewing")
        svc = WeeklyReportService(db)
        b2b = svc.generate_report()["b2b_summary"]
        assert b2b["total"] == 2
        assert b2b["status_distribution"]["new"] == 1


# ─── 하이라이트 ──────────────────────────────────────────────

class TestHighlights:
    def test_high_value_items(self, db):
        src = _make_source(db)
        _make_draft(db, src, hook="High value", monetization_score=85)
        _make_draft(db, src, hook="Low value", monetization_score=30)
        svc = WeeklyReportService(db)
        highlights = svc.generate_report()["highlights"]
        assert len(highlights) == 1
        assert highlights[0]["monetization_score"] == 85

    def test_old_items_excluded(self, db):
        src = _make_source(db)
        _make_draft(db, src, monetization_score=90, created_days_ago=10)
        svc = WeeklyReportService(db)
        highlights = svc.generate_report(days=7)["highlights"]
        assert len(highlights) == 0

    def test_sorted_by_score(self, db):
        src = _make_source(db)
        _make_draft(db, src, hook="Lower", monetization_score=75)
        _make_draft(db, src, hook="Higher", monetization_score=95)
        svc = WeeklyReportService(db)
        highlights = svc.generate_report()["highlights"]
        assert highlights[0]["monetization_score"] == 95


# ─── 후속 조치 ───────────────────────────────────────────────

class TestFollowupItems:
    def test_pending_approval(self, db):
        src = _make_source(db)
        _make_draft(db, src, approval_status=ApprovalStatus.PENDING)
        svc = WeeklyReportService(db)
        followups = svc.generate_report()["followup_items"]
        actions = [f["action"] for f in followups]
        assert "review_pending" in actions

    def test_new_premium(self, db):
        src = _make_source(db)
        _make_draft(db, src, business_tags=["premium_candidate"],
                    premium_status="new")
        svc = WeeklyReportService(db)
        followups = svc.generate_report()["followup_items"]
        actions = [f["action"] for f in followups]
        assert "review_premium" in actions

    def test_new_b2b(self, db):
        src = _make_source(db)
        _make_draft(db, src, b2b_candidate=True, b2b_status="new")
        svc = WeeklyReportService(db)
        followups = svc.generate_report()["followup_items"]
        actions = [f["action"] for f in followups]
        assert "review_b2b" in actions

    def test_lead_without_name(self, db):
        src = _make_source(db)
        _make_draft(db, src, cta_type="lead_magnet")
        svc = WeeklyReportService(db)
        followups = svc.generate_report()["followup_items"]
        actions = [f["action"] for f in followups]
        assert "set_lead_asset" in actions

    def test_no_followups_when_clean(self, db):
        src = _make_source(db)
        _make_draft(db, src)
        svc = WeeklyReportService(db)
        followups = svc.generate_report()["followup_items"]
        assert len(followups) == 0


# ─── 포맷 ────────────────────────────────────────────────────

class TestFormatReport:
    def test_format_report_contains_sections(self, db):
        src = _make_source(db)
        _make_draft(db, src, hook="Format test",
                    business_tags=["premium_candidate", "growth"],
                    premium_status="new", monetization_score=80,
                    email_bucket="weekly_free", cta_type="newsletter_signup")
        svc = WeeklyReportService(db)
        report = svc.generate_report()
        text = svc.format_report(report)
        assert "주간 운영 리포트" in text
        assert "콘텐츠" in text
        assert "뉴스레터" in text
        assert "프리미엄" in text

    def test_format_compact(self, db):
        src = _make_source(db)
        _make_draft(db, src)
        svc = WeeklyReportService(db)
        report = svc.generate_report()
        text = svc.format_compact(report)
        assert "주간 요약" in text
        assert "초안" in text

    def test_format_empty(self, db):
        svc = WeeklyReportService(db)
        report = svc.generate_report()
        text = svc.format_report(report)
        assert "주간 운영 리포트" in text
        text2 = svc.format_compact(report)
        assert "주간 요약" in text2


# ─── 내보내기 ────────────────────────────────────────────────

class TestExport:
    def test_export_equals_generate(self, db):
        svc = WeeklyReportService(db)
        report = svc.generate_report()
        exported = svc.export_report()
        assert report.keys() == exported.keys()

    def test_export_is_serializable(self, db):
        src = _make_source(db)
        _make_draft(db, src, business_tags=["growth"], monetization_score=80)
        svc = WeeklyReportService(db)
        exported = svc.export_report()
        text = json.dumps(exported, ensure_ascii=False)
        assert len(text) > 0


# ─── CTA 카피 성과 섹션 ─────────────────────────────────────

def _make_cta_copy(db, cta_type="newsletter_signup", copy_text="Test CTA"):
    copy = CtaCopy(
        cta_type=cta_type, copy_text=copy_text, is_active=True,
    )
    db.add(copy)
    db.commit()
    db.refresh(copy)
    return copy


def _make_linked_draft(db, source, cta_copy, hook="Linked Draft",
                       approval_status=ApprovalStatus.PUBLISHED,
                       monetization_score=None, x_post_id=None):
    draft = Draft(
        source_item_id=source.id, hook=hook,
        body="Test body", category=ContentCategory.ECONOMY,
        risk_level=RiskLevel.LOW,
        approval_status=approval_status,
        monetization_score=monetization_score,
        x_post_id=x_post_id,
        cta_copy_id=cta_copy.id,
        created_at=datetime.now(timezone.utc),
    )
    db.add(draft)
    db.commit()
    db.refresh(draft)
    return draft


class TestCtaPerfSummary:
    def test_report_has_cta_perf_section(self, db):
        svc = WeeklyReportService(db)
        report = svc.generate_report()
        assert "cta_perf_summary" in report

    def test_empty_when_no_copies(self, db):
        svc = WeeklyReportService(db)
        cta = svc.generate_report()["cta_perf_summary"]
        assert cta["total_copies"] == 0
        assert cta["linked_copies"] == 0

    def test_counts_copies(self, db):
        src = _make_source(db)
        c1 = _make_cta_copy(db, "newsletter_signup", "NL CTA")
        c2 = _make_cta_copy(db, "lead_magnet", "LM CTA")
        _make_linked_draft(db, src, c1)
        _make_linked_draft(db, src, c1)
        svc = WeeklyReportService(db)
        cta = svc.generate_report()["cta_perf_summary"]
        assert cta["total_copies"] == 2
        assert cta["linked_copies"] == 1
        assert cta["unlinked_copies"] == 1
        assert cta["total_linked_drafts"] == 2

    def test_published_and_posted(self, db):
        src = _make_source(db)
        c1 = _make_cta_copy(db, "newsletter_signup", "NL CTA")
        _make_linked_draft(db, src, c1, approval_status=ApprovalStatus.PUBLISHED,
                           x_post_id="tweet123")
        _make_linked_draft(db, src, c1, approval_status=ApprovalStatus.REJECTED)
        svc = WeeklyReportService(db)
        cta = svc.generate_report()["cta_perf_summary"]
        assert cta["total_published"] == 1
        assert cta["total_posted_to_x"] == 1

    def test_type_usage(self, db):
        src = _make_source(db)
        c1 = _make_cta_copy(db, "newsletter_signup", "NL")
        c2 = _make_cta_copy(db, "premium_teaser", "PT")
        _make_linked_draft(db, src, c1)
        _make_linked_draft(db, src, c1)
        _make_linked_draft(db, src, c2)
        svc = WeeklyReportService(db)
        cta = svc.generate_report()["cta_perf_summary"]
        assert cta["type_usage"]["newsletter_signup"] == 2
        assert cta["type_usage"]["premium_teaser"] == 1

    def test_top_copies(self, db):
        src = _make_source(db)
        c1 = _make_cta_copy(db, "newsletter_signup", "Top CTA")
        _make_linked_draft(db, src, c1)
        _make_linked_draft(db, src, c1)
        svc = WeeklyReportService(db)
        cta = svc.generate_report()["cta_perf_summary"]
        assert len(cta["top_copies"]) == 1
        assert cta["top_copies"][0]["copy_id"] == c1.id
        assert cta["top_copies"][0]["total_linked"] == 2

    def test_notable_high_monetization(self, db):
        src = _make_source(db)
        c1 = _make_cta_copy(db, "premium_teaser", "Premium CTA")
        _make_linked_draft(db, src, c1, monetization_score=85)
        svc = WeeklyReportService(db)
        cta = svc.generate_report()["cta_perf_summary"]
        assert len(cta["notable_copies"]) == 1
        assert cta["notable_copies"][0]["avg_monetization"] >= 70

    def test_notable_high_pub_rate(self, db):
        src = _make_source(db)
        c1 = _make_cta_copy(db, "newsletter_signup", "Good CTA")
        _make_linked_draft(db, src, c1, approval_status=ApprovalStatus.PUBLISHED)
        _make_linked_draft(db, src, c1, approval_status=ApprovalStatus.PUBLISHED)
        svc = WeeklyReportService(db)
        cta = svc.generate_report()["cta_perf_summary"]
        assert len(cta["notable_copies"]) == 1

    def test_export_includes_cta_perf(self, db):
        src = _make_source(db)
        c1 = _make_cta_copy(db, "newsletter_signup", "Export CTA")
        _make_linked_draft(db, src, c1)
        svc = WeeklyReportService(db)
        exported = svc.export_report()
        assert "cta_perf_summary" in exported
        text = json.dumps(exported, ensure_ascii=False)
        assert "cta_perf_summary" in text


class TestCtaPerfFormat:
    def test_format_report_includes_cta(self, db):
        src = _make_source(db)
        c1 = _make_cta_copy(db, "newsletter_signup", "NL CTA for format")
        _make_linked_draft(db, src, c1)
        svc = WeeklyReportService(db)
        report = svc.generate_report()
        text = svc.format_report(report)
        assert "CTA 카피 성과" in text

    def test_format_report_skips_when_empty(self, db):
        svc = WeeklyReportService(db)
        report = svc.generate_report()
        text = svc.format_report(report)
        assert "CTA 카피 성과" not in text

    def test_compact_includes_cta(self, db):
        src = _make_source(db)
        c1 = _make_cta_copy(db, "newsletter_signup", "NL CTA compact")
        _make_linked_draft(db, src, c1)
        svc = WeeklyReportService(db)
        report = svc.generate_report()
        text = svc.format_compact(report)
        assert "CTA 카피" in text

    def test_compact_skips_when_no_linked(self, db):
        _make_cta_copy(db, "newsletter_signup", "Unlinked CTA")
        svc = WeeklyReportService(db)
        report = svc.generate_report()
        text = svc.format_compact(report)
        assert "CTA 카피" not in text
