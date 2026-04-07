"""
TopicMemory 테스트
==================
태그 빈도 집계, 과다 사용 감지, 믹스 리포트 포맷 검증.
모든 테스트는 인메모리 SQLite를 사용합니다.
"""

import json
import pytest
from datetime import datetime, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.services.topic_memory import TopicMemory


# ─── 테스트용 DB 픽스처 ──────────────────────────────────────────────────────

@pytest.fixture
def db_session():
    """인메모리 SQLite 세션 + 스키마 초기화."""
    from app.models.content import Base
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def _insert_draft(session, topic_tags: list[str], status: str = "approved"):
    """테스트용 Draft 레코드 삽입 헬퍼."""
    from app.models.content import Draft, ApprovalStatus, ContentCategory, RiskLevel
    draft = Draft(
        source_item_id=1,
        hook="test hook",
        body="test body",
        category=ContentCategory.ECONOMY,
        risk_level=RiskLevel.LOW,
        approval_status=ApprovalStatus.APPROVED if status == "approved" else ApprovalStatus.PUBLISHED,
        topic_tags=json.dumps(topic_tags),
        created_at=datetime.now(timezone.utc),
    )
    session.add(draft)
    session.commit()
    return draft


# ─── get_recent_tags ─────────────────────────────────────────────────────────

class TestGetRecentTags:
    def test_empty_db_returns_empty_counter(self, db_session):
        memory = TopicMemory(db_session)
        counter = memory.get_recent_tags(days=30)
        assert len(counter) == 0

    def test_counts_single_draft_tags(self, db_session):
        _insert_draft(db_session, ["economy", "BOK", "rates"])
        memory = TopicMemory(db_session)
        counter = memory.get_recent_tags(days=30)
        assert counter["economy"] == 1
        assert counter["bok"] == 1
        assert counter["rates"] == 1

    def test_aggregates_across_multiple_drafts(self, db_session):
        _insert_draft(db_session, ["economy", "BOK"])
        _insert_draft(db_session, ["economy", "crypto"])
        _insert_draft(db_session, ["economy"])
        memory = TopicMemory(db_session)
        counter = memory.get_recent_tags(days=30)
        assert counter["economy"] == 3
        assert counter["bok"] == 1
        assert counter["crypto"] == 1

    def test_tags_are_lowercased(self, db_session):
        _insert_draft(db_session, ["Economy", "BOK", "CRYPTO"])
        memory = TopicMemory(db_session)
        counter = memory.get_recent_tags(days=30)
        assert "economy" in counter
        assert "bok" in counter
        assert "crypto" in counter
        # 원본 케이스는 없어야 함
        assert "Economy" not in counter

    def test_ignores_pending_drafts(self, db_session):
        from app.models.content import Draft, ApprovalStatus, ContentCategory, RiskLevel
        # pending 상태 (승인 안 됨)
        draft = Draft(
            source_item_id=1,
            hook="h", body="b",
            category=ContentCategory.ECONOMY,
            risk_level=RiskLevel.LOW,
            approval_status=ApprovalStatus.PENDING,
            topic_tags=json.dumps(["economy"]),
            created_at=datetime.now(timezone.utc),
        )
        db_session.add(draft)
        db_session.commit()
        memory = TopicMemory(db_session)
        counter = memory.get_recent_tags(days=30)
        assert counter["economy"] == 0

    def test_handles_malformed_json_gracefully(self, db_session):
        from app.models.content import Draft, ApprovalStatus, ContentCategory, RiskLevel
        draft = Draft(
            source_item_id=1,
            hook="h", body="b",
            category=ContentCategory.ECONOMY,
            risk_level=RiskLevel.LOW,
            approval_status=ApprovalStatus.APPROVED,
            topic_tags="not_valid_json[[[",
            created_at=datetime.now(timezone.utc),
        )
        db_session.add(draft)
        db_session.commit()
        # 예외 없이 빈 Counter 반환
        memory = TopicMemory(db_session)
        counter = memory.get_recent_tags(days=30)
        assert isinstance(counter, dict)

    def test_handles_null_topic_tags(self, db_session):
        from app.models.content import Draft, ApprovalStatus, ContentCategory, RiskLevel
        draft = Draft(
            source_item_id=1,
            hook="h", body="b",
            category=ContentCategory.ECONOMY,
            risk_level=RiskLevel.LOW,
            approval_status=ApprovalStatus.APPROVED,
            topic_tags=None,
            created_at=datetime.now(timezone.utc),
        )
        db_session.add(draft)
        db_session.commit()
        memory = TopicMemory(db_session)
        counter = memory.get_recent_tags(days=30)
        assert isinstance(counter, dict)


# ─── get_overused_tags ────────────────────────────────────────────────────────

class TestGetOverusedTags:
    def test_returns_empty_when_no_tags(self, db_session):
        memory = TopicMemory(db_session)
        result = memory.get_overused_tags(threshold=3)
        assert result == []

    def test_returns_tag_exceeding_threshold(self, db_session):
        for _ in range(6):
            _insert_draft(db_session, ["economy"])
        _insert_draft(db_session, ["crypto"])  # 1번만

        memory = TopicMemory(db_session)
        overused = memory.get_overused_tags(threshold=5)
        assert "economy" in overused
        assert "crypto" not in overused

    def test_threshold_boundary_exclusive(self, db_session):
        # threshold=5 → count=5는 포함 안 됨 (> 5이어야 포함)
        for _ in range(5):
            _insert_draft(db_session, ["economy"])
        memory = TopicMemory(db_session)
        overused = memory.get_overused_tags(threshold=5)
        assert "economy" not in overused

    def test_threshold_boundary_inclusive_plus_one(self, db_session):
        for _ in range(6):
            _insert_draft(db_session, ["economy"])
        memory = TopicMemory(db_session)
        overused = memory.get_overused_tags(threshold=5)
        assert "economy" in overused

    def test_returns_sorted_by_frequency(self, db_session):
        for _ in range(8):
            _insert_draft(db_session, ["economy"])
        for _ in range(6):
            _insert_draft(db_session, ["BOK"])
        memory = TopicMemory(db_session)
        overused = memory.get_overused_tags(threshold=5)
        assert overused[0] == "economy"  # 가장 빈도 높은 것이 먼저


# ─── format_mix_report ────────────────────────────────────────────────────────

class TestFormatMixReport:
    def test_empty_db_returns_empty_string(self, db_session):
        memory = TopicMemory(db_session)
        result = memory.format_mix_report(days=7)
        assert result == ""

    def test_populated_db_returns_nonempty_string(self, db_session):
        _insert_draft(db_session, ["economy", "BOK"])
        memory = TopicMemory(db_session)
        result = memory.format_mix_report(days=30)
        assert result != ""
        assert "📌" in result
        assert "economy" in result

    def test_includes_overuse_warning_when_threshold_met(self, db_session):
        for _ in range(6):
            _insert_draft(db_session, ["economy"])
        memory = TopicMemory(db_session)
        result = memory.format_mix_report(days=30)
        assert "⚠️" in result
        assert "economy" in result

    def test_no_overuse_warning_below_threshold(self, db_session):
        for _ in range(3):
            _insert_draft(db_session, ["economy"])
        memory = TopicMemory(db_session)
        result = memory.format_mix_report(days=30)
        # ⚠️ 없어야 함 (3회는 임계값 5 미만)
        assert "⚠️" not in result

    def test_format_includes_count_notation(self, db_session):
        _insert_draft(db_session, ["economy"])
        _insert_draft(db_session, ["economy"])
        memory = TopicMemory(db_session)
        result = memory.format_mix_report(days=30)
        assert "economy×2" in result

    def test_format_includes_days_label(self, db_session):
        _insert_draft(db_session, ["economy"])
        memory = TopicMemory(db_session)
        result = memory.format_mix_report(days=7)
        assert "7일" in result
