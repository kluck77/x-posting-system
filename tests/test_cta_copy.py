"""
CTA 카피 블록 서비스 테스트
==============================
CtaCopyService CRUD, 활성/비활성, 연결, 내보내기, 포맷 검증.
"""

import pytest
from datetime import datetime, timezone
from app.models.content import (
    Base, Draft, SourceItem, CtaCopy, PostLog,
    ContentCategory, RiskLevel, ApprovalStatus,
)
from app.services.cta_copy_service import (
    CtaCopyService,
    CTA_COPY_TYPES,
)


@pytest.fixture
def db(db_session):
    return db_session


def _make_source(db, title="CTA Copy Test Source"):
    src = SourceItem(
        title=title, source_text="test text", source_type="manual",
        language="ko", created_at=datetime.now(timezone.utc),
    )
    db.add(src)
    db.commit()
    db.refresh(src)
    return src


def _make_draft(db, source, hook="Test Hook"):
    draft = Draft(
        source_item_id=source.id, hook=hook,
        body="Test body", category=ContentCategory.ECONOMY,
        risk_level=RiskLevel.LOW,
        approval_status=ApprovalStatus.PUBLISHED,
        created_at=datetime.now(timezone.utc),
    )
    db.add(draft)
    db.commit()
    db.refresh(draft)
    return draft


# ─── 상수 테스트 ──────────────────────────────────────────────

class TestConstants:
    def test_cta_copy_types(self):
        expected = (
            "newsletter_signup", "lead_magnet", "premium_teaser",
            "premium_waitlist", "b2b_inquiry",
        )
        assert CTA_COPY_TYPES == expected


# ─── 추가 ────────────────────────────────────────────────────

class TestAddCopy:
    def test_add_valid(self, db):
        svc = CtaCopyService(db)
        copy = svc.add_copy("newsletter_signup", "Get weekly Korea insights free!")
        assert copy is not None
        assert copy.id is not None
        assert copy.cta_type == "newsletter_signup"
        assert copy.copy_text == "Get weekly Korea insights free!"
        assert copy.is_active is True

    def test_add_with_note(self, db):
        svc = CtaCopyService(db)
        copy = svc.add_copy("lead_magnet", "Download the checklist", note="For labor law page")
        assert copy is not None
        assert copy.note == "For labor law page"

    def test_add_invalid_type(self, db):
        svc = CtaCopyService(db)
        assert svc.add_copy("invalid_type", "text") is None

    def test_add_empty_text(self, db):
        svc = CtaCopyService(db)
        assert svc.add_copy("newsletter_signup", "") is None
        assert svc.add_copy("newsletter_signup", "   ") is None

    def test_add_truncates_text(self, db):
        svc = CtaCopyService(db)
        copy = svc.add_copy("newsletter_signup", "A" * 2000)
        assert len(copy.copy_text) == 1000

    def test_add_truncates_note(self, db):
        svc = CtaCopyService(db)
        copy = svc.add_copy("newsletter_signup", "text", note="N" * 600)
        assert len(copy.note) == 500


# ─── 조회 ────────────────────────────────────────────────────

class TestGet:
    def test_get_by_id(self, db):
        svc = CtaCopyService(db)
        copy = svc.add_copy("newsletter_signup", "Test copy")
        result = svc.get_by_id(copy.id)
        assert result is not None
        assert result.copy_text == "Test copy"

    def test_get_by_id_nonexistent(self, db):
        svc = CtaCopyService(db)
        assert svc.get_by_id(9999) is None

    def test_get_all(self, db):
        svc = CtaCopyService(db)
        svc.add_copy("newsletter_signup", "Copy 1")
        svc.add_copy("lead_magnet", "Copy 2")
        svc.add_copy("premium_teaser", "Copy 3")
        result = svc.get_all()
        assert len(result) == 3

    def test_get_all_active_only(self, db):
        svc = CtaCopyService(db)
        c1 = svc.add_copy("newsletter_signup", "Active")
        c2 = svc.add_copy("newsletter_signup", "Inactive")
        svc.deactivate(c2.id)
        result = svc.get_all(active_only=True)
        assert len(result) == 1
        assert result[0].copy_text == "Active"

    def test_get_by_type(self, db):
        svc = CtaCopyService(db)
        svc.add_copy("newsletter_signup", "NL 1")
        svc.add_copy("newsletter_signup", "NL 2")
        svc.add_copy("lead_magnet", "LM 1")
        result = svc.get_by_type("newsletter_signup")
        assert len(result) == 2

    def test_get_by_type_active_only(self, db):
        svc = CtaCopyService(db)
        c1 = svc.add_copy("newsletter_signup", "Active NL")
        c2 = svc.add_copy("newsletter_signup", "Inactive NL")
        svc.deactivate(c2.id)
        result = svc.get_by_type("newsletter_signup", active_only=True)
        assert len(result) == 1

    def test_count_by_type(self, db):
        svc = CtaCopyService(db)
        svc.add_copy("newsletter_signup", "NL")
        svc.add_copy("newsletter_signup", "NL2")
        svc.add_copy("lead_magnet", "LM")
        c = svc.add_copy("premium_teaser", "PT")
        svc.deactivate(c.id)
        counts = svc.count_by_type()
        assert counts["newsletter_signup"] == 2
        assert counts["lead_magnet"] == 1
        assert "premium_teaser" not in counts  # inactive excluded


# ─── 수정 ────────────────────────────────────────────────────

class TestEdit:
    def test_edit_copy(self, db):
        svc = CtaCopyService(db)
        copy = svc.add_copy("newsletter_signup", "Old text")
        result = svc.edit_copy(copy.id, "New text")
        assert result is not None
        assert result.copy_text == "New text"

    def test_edit_truncates(self, db):
        svc = CtaCopyService(db)
        copy = svc.add_copy("newsletter_signup", "Old")
        result = svc.edit_copy(copy.id, "X" * 2000)
        assert len(result.copy_text) == 1000

    def test_edit_empty_fails(self, db):
        svc = CtaCopyService(db)
        copy = svc.add_copy("newsletter_signup", "Existing")
        assert svc.edit_copy(copy.id, "") is None
        assert svc.edit_copy(copy.id, "   ") is None

    def test_edit_nonexistent(self, db):
        svc = CtaCopyService(db)
        assert svc.edit_copy(9999, "new text") is None

    def test_set_note(self, db):
        svc = CtaCopyService(db)
        copy = svc.add_copy("newsletter_signup", "Text")
        result = svc.set_note(copy.id, "Some note")
        assert result is not None
        assert result.note == "Some note"

    def test_set_note_truncates(self, db):
        svc = CtaCopyService(db)
        copy = svc.add_copy("newsletter_signup", "Text")
        result = svc.set_note(copy.id, "N" * 600)
        assert len(result.note) == 500

    def test_set_note_nonexistent(self, db):
        svc = CtaCopyService(db)
        assert svc.set_note(9999, "note") is None


# ─── 활성/비활성 ─────────────────────────────────────────────

class TestToggle:
    def test_deactivate(self, db):
        svc = CtaCopyService(db)
        copy = svc.add_copy("newsletter_signup", "Active copy")
        assert copy.is_active is True
        result = svc.deactivate(copy.id)
        assert result.is_active is False

    def test_activate(self, db):
        svc = CtaCopyService(db)
        copy = svc.add_copy("newsletter_signup", "Copy")
        svc.deactivate(copy.id)
        result = svc.activate(copy.id)
        assert result.is_active is True

    def test_deactivate_nonexistent(self, db):
        svc = CtaCopyService(db)
        assert svc.deactivate(9999) is None

    def test_activate_nonexistent(self, db):
        svc = CtaCopyService(db)
        assert svc.activate(9999) is None


# ─── 드래프트 연결 ───────────────────────────────────────────

class TestLink:
    def test_link_to_draft(self, db):
        src = _make_source(db)
        draft = _make_draft(db, src)
        svc = CtaCopyService(db)
        copy = svc.add_copy("newsletter_signup", "CTA text")
        result = svc.link_to_draft(draft.id, copy.id)
        assert result is not None
        assert result.cta_copy_id == copy.id

    def test_link_nonexistent_copy(self, db):
        src = _make_source(db)
        draft = _make_draft(db, src)
        svc = CtaCopyService(db)
        assert svc.link_to_draft(draft.id, 9999) is None

    def test_link_nonexistent_draft(self, db):
        svc = CtaCopyService(db)
        copy = svc.add_copy("newsletter_signup", "Text")
        assert svc.link_to_draft(9999, copy.id) is None

    def test_unlink(self, db):
        src = _make_source(db)
        draft = _make_draft(db, src)
        svc = CtaCopyService(db)
        copy = svc.add_copy("newsletter_signup", "CTA")
        svc.link_to_draft(draft.id, copy.id)
        result = svc.unlink_from_draft(draft.id)
        assert result is not None
        assert result.cta_copy_id is None

    def test_unlink_nonexistent(self, db):
        svc = CtaCopyService(db)
        assert svc.unlink_from_draft(9999) is None


# ─── 내보내기 ────────────────────────────────────────────────

class TestExport:
    def test_export_structure(self, db):
        svc = CtaCopyService(db)
        svc.add_copy("newsletter_signup", "NL copy", note="For main page")
        items = svc.export_copies()
        assert len(items) == 1
        item = items[0]
        assert "id" in item
        assert item["cta_type"] == "newsletter_signup"
        assert item["copy_text"] == "NL copy"
        assert item["note"] == "For main page"
        assert item["is_active"] is True
        assert "created_at" in item
        assert "updated_at" in item

    def test_export_active_only(self, db):
        svc = CtaCopyService(db)
        svc.add_copy("newsletter_signup", "Active")
        c2 = svc.add_copy("newsletter_signup", "Inactive")
        svc.deactivate(c2.id)
        items = svc.export_copies(active_only=True)
        assert len(items) == 1
        assert items[0]["is_active"] is True

    def test_export_empty(self, db):
        svc = CtaCopyService(db)
        assert svc.export_copies() == []


# ─── 포맷 ────────────────────────────────────────────────────

class TestFormat:
    def test_summary_empty(self, db):
        svc = CtaCopyService(db)
        text = svc.format_summary()
        assert "비어있음" in text

    def test_summary_with_data(self, db):
        svc = CtaCopyService(db)
        svc.add_copy("newsletter_signup", "NL copy")
        svc.add_copy("lead_magnet", "LM copy")
        text = svc.format_summary()
        assert "카피 라이브러리" in text
        assert "Newsletter" in text
        assert "Lead Magnet" in text

    def test_detail(self, db):
        svc = CtaCopyService(db)
        copy = svc.add_copy(
            "premium_teaser", "Unlock Korea insights",
            note="For premium landing",
        )
        text = svc.format_copy_detail(copy)
        assert str(copy.id) in text
        assert "premium_teaser" in text
        assert "Unlock Korea insights" in text
        assert "For premium landing" in text
        assert "활성" in text

    def test_detail_inactive(self, db):
        svc = CtaCopyService(db)
        copy = svc.add_copy("newsletter_signup", "Text")
        svc.deactivate(copy.id)
        copy = svc.get_by_id(copy.id)
        text = svc.format_copy_detail(copy)
        assert "비활성" in text


# ─── 성과 추적 ──────────────────────────────────────────────

def _make_linked_draft(db, source, copy, hook="Linked Hook",
                       approval_status=ApprovalStatus.PUBLISHED,
                       monetization_score=None, x_post_id=None):
    draft = Draft(
        source_item_id=source.id, hook=hook,
        body="Test body", category=ContentCategory.ECONOMY,
        risk_level=RiskLevel.LOW,
        approval_status=approval_status,
        monetization_score=monetization_score,
        x_post_id=x_post_id,
        cta_copy_id=copy.id,
        created_at=datetime.now(timezone.utc),
    )
    db.add(draft)
    db.commit()
    db.refresh(draft)
    return draft


class TestGetLinkedDrafts:
    def test_no_linked(self, db):
        svc = CtaCopyService(db)
        copy = svc.add_copy("newsletter_signup", "Copy text")
        assert svc.get_linked_drafts(copy.id) == []

    def test_with_linked(self, db):
        svc = CtaCopyService(db)
        src = _make_source(db)
        copy = svc.add_copy("newsletter_signup", "Copy text")
        _make_linked_draft(db, src, copy, hook="Draft 1")
        _make_linked_draft(db, src, copy, hook="Draft 2")
        result = svc.get_linked_drafts(copy.id)
        assert len(result) == 2

    def test_limit(self, db):
        svc = CtaCopyService(db)
        src = _make_source(db)
        copy = svc.add_copy("newsletter_signup", "Copy text")
        for i in range(5):
            _make_linked_draft(db, src, copy, hook=f"Draft {i}")
        result = svc.get_linked_drafts(copy.id, limit=3)
        assert len(result) == 3


class TestGetCopyPerf:
    def test_nonexistent(self, db):
        svc = CtaCopyService(db)
        assert svc.get_copy_perf(9999) is None

    def test_no_drafts(self, db):
        svc = CtaCopyService(db)
        copy = svc.add_copy("newsletter_signup", "Copy text")
        perf = svc.get_copy_perf(copy.id)
        assert perf is not None
        assert perf["total_linked"] == 0
        assert perf["published"] == 0
        assert perf["avg_monetization"] == 0

    def test_with_drafts(self, db):
        svc = CtaCopyService(db)
        src = _make_source(db)
        copy = svc.add_copy("newsletter_signup", "Copy text")
        _make_linked_draft(db, src, copy, approval_status=ApprovalStatus.PUBLISHED,
                           monetization_score=80, x_post_id="123")
        _make_linked_draft(db, src, copy, approval_status=ApprovalStatus.APPROVED,
                           monetization_score=60)
        _make_linked_draft(db, src, copy, approval_status=ApprovalStatus.REJECTED,
                           monetization_score=40)
        perf = svc.get_copy_perf(copy.id)
        assert perf["total_linked"] == 3
        assert perf["published"] == 1
        assert perf["approved"] == 1
        assert perf["rejected"] == 1
        assert perf["posted_to_x"] == 1
        assert perf["avg_monetization"] == 60
        assert perf["high_value_count"] == 1

    def test_perf_structure(self, db):
        svc = CtaCopyService(db)
        copy = svc.add_copy("lead_magnet", "Download now")
        perf = svc.get_copy_perf(copy.id)
        expected_keys = {
            "copy_id", "cta_type", "copy_text", "is_active", "note",
            "total_linked", "published", "approved", "rejected",
            "posted_to_x", "avg_monetization", "high_value_count",
            "recent_drafts",
        }
        assert set(perf.keys()) == expected_keys

    def test_recent_drafts_limit(self, db):
        svc = CtaCopyService(db)
        src = _make_source(db)
        copy = svc.add_copy("newsletter_signup", "Copy")
        for i in range(8):
            _make_linked_draft(db, src, copy, hook=f"Draft {i}")
        perf = svc.get_copy_perf(copy.id)
        assert len(perf["recent_drafts"]) <= 5


class TestGetAllPerf:
    def test_empty(self, db):
        svc = CtaCopyService(db)
        assert svc.get_all_perf() == []

    def test_multiple_copies(self, db):
        svc = CtaCopyService(db)
        src = _make_source(db)
        c1 = svc.add_copy("newsletter_signup", "NL copy")
        c2 = svc.add_copy("lead_magnet", "LM copy")
        _make_linked_draft(db, src, c1)
        _make_linked_draft(db, src, c1)
        _make_linked_draft(db, src, c2)
        result = svc.get_all_perf()
        assert len(result) == 2
        # sorted by total_linked desc
        assert result[0]["copy_id"] == c1.id
        assert result[0]["total_linked"] == 2


class TestExportPerf:
    def test_export_matches_all_perf(self, db):
        svc = CtaCopyService(db)
        src = _make_source(db)
        copy = svc.add_copy("newsletter_signup", "Copy")
        _make_linked_draft(db, src, copy)
        export = svc.export_perf()
        all_perf = svc.get_all_perf()
        assert len(export) == len(all_perf)


class TestFormatPerf:
    def test_summary_empty(self, db):
        svc = CtaCopyService(db)
        text = svc.format_perf_summary()
        assert "없음" in text

    def test_summary_with_data(self, db):
        svc = CtaCopyService(db)
        src = _make_source(db)
        copy = svc.add_copy("newsletter_signup", "NL copy text")
        _make_linked_draft(db, src, copy, monetization_score=75)
        text = svc.format_perf_summary()
        assert "성과 요약" in text
        assert "연결" in text

    def test_detail(self, db):
        svc = CtaCopyService(db)
        src = _make_source(db)
        copy = svc.add_copy("premium_teaser", "Unlock insights")
        _make_linked_draft(db, src, copy, approval_status=ApprovalStatus.PUBLISHED,
                           monetization_score=85, x_post_id="abc123")
        perf = svc.get_copy_perf(copy.id)
        text = svc.format_perf_detail(perf)
        assert str(copy.id) in text
        assert "premium_teaser" in text
        assert "게시" in text
        assert "수익화" in text

    def test_detail_no_linked(self, db):
        svc = CtaCopyService(db)
        copy = svc.add_copy("newsletter_signup", "Text")
        perf = svc.get_copy_perf(copy.id)
        text = svc.format_perf_detail(perf)
        assert "0건" in text
