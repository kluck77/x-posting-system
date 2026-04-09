"""
tests/test_dedup_persistence.py
================================
Dedup/Candidate Pool DB 영속화 테스트.
실제 SQLite 임시 DB 를 사용하여 write-through + 복원 흐름 검증.
"""

import json
import os
import time
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

# 테스트용 임시 DB 설정 (인메모리 SQLite)
_TEST_DB_URL = "sqlite:///./test_dedup_persistence.db"

from app.models.content import Base
from app.models.dedup import BreakingDedupEntry, BreakingSentKey, CandidatePoolEntry

# --- 테스트용 DB 엔진/세션 ---
_test_engine = create_engine(_TEST_DB_URL, connect_args={"check_same_thread": False})

@event.listens_for(_test_engine, "connect")
def _set_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()

_TestSession = sessionmaker(autocommit=False, autoflush=False, bind=_test_engine)


@pytest.fixture(autouse=True)
def _setup_test_db(monkeypatch):
    """매 테스트마다 깨끗한 DB + 서비스 모듈 패치."""
    # 테이블 생성
    Base.metadata.create_all(bind=_test_engine)

    # app.db.get_db 를 테스트 DB 세션으로 패치
    def _get_test_db():
        return _TestSession()

    import app.db
    monkeypatch.setattr(app.db, "get_db", _get_test_db)

    # 인메모리 저장소 초기화
    from app.services.breaking_alert_service import _reset_dedup_store_for_tests
    from app.services.top5_briefing_service import _reset_stores_for_tests
    _reset_dedup_store_for_tests()
    _reset_stores_for_tests()

    yield

    # 테이블 삭제
    Base.metadata.drop_all(bind=_test_engine)

    # 인메모리 저장소 초기화
    _reset_dedup_store_for_tests()
    _reset_stores_for_tests()


@pytest.fixture(autouse=True)
def _cleanup_test_db_file():
    """테스트 DB 파일 정리."""
    yield
    for suffix in ("", "-wal", "-shm"):
        path = "./test_dedup_persistence.db" + suffix
        if os.path.exists(path):
            os.remove(path)


# ---------------------------------------------------------------------------
# BREAKING dedup 영속화 테스트
# ---------------------------------------------------------------------------
class TestBreakingDedupPersistence:
    def test_record_sent_persists_to_db(self):
        """_record_sent → DB 에 기록됨."""
        from app.services.breaking_alert_service import _record_sent

        _record_sent("test:key:001", time.time())

        db = _TestSession()
        try:
            rows = db.query(BreakingDedupEntry).all()
            assert len(rows) == 1
            assert rows[0].issue_key == "test:key:001"
        finally:
            db.close()

    def test_load_dedup_restores_memory(self):
        """DB 에 있던 데이터가 메모리로 복원됨."""
        now = time.time()

        # DB 에 직접 삽입
        db = _TestSession()
        db.add(BreakingDedupEntry(issue_key="restore:key:001", sent_at=now))
        db.commit()
        db.close()

        # 메모리 로드
        from app.services.breaking_alert_service import (
            _dedup_store,
            _load_dedup_from_db,
        )
        _load_dedup_from_db()

        assert "restore:key:001" in _dedup_store
        assert abs(_dedup_store["restore:key:001"] - now) < 1

    def test_load_skips_expired_entries(self):
        """6h 윈도우 밖 항목은 로드 안 됨."""
        expired = time.time() - (7 * 3600)  # 7시간 전

        db = _TestSession()
        db.add(BreakingDedupEntry(issue_key="expired:key", sent_at=expired))
        db.commit()
        db.close()

        from app.services.breaking_alert_service import (
            _dedup_store,
            _load_dedup_from_db,
        )
        _load_dedup_from_db()

        assert "expired:key" not in _dedup_store

    def test_dedup_survives_restart_simulation(self):
        """기록 → 메모리 초기화 → DB 로드 → dedup 판정 유지."""
        from app.services.breaking_alert_service import (
            _is_duplicate_within_window,
            _record_sent,
            _reset_dedup_store_for_tests,
        )

        now = time.time()
        _record_sent("restart:test:key", now)

        # "재시작" 시뮬레이션: 메모리 초기화
        _reset_dedup_store_for_tests()

        # DB 에서 복원되어 dedup 차단되어야 함
        assert _is_duplicate_within_window("restart:test:key", now + 10) is True


# ---------------------------------------------------------------------------
# CANDIDATE pool 영속화 테스트
# ---------------------------------------------------------------------------
_KST = timezone(timedelta(hours=9))


class TestCandidatePoolPersistence:
    def test_record_candidate_persists_to_db(self):
        """record_candidate → DB 에 기록됨."""
        from app.services.top5_briefing_service import record_candidate

        record_candidate(
            title="테스트 기사",
            body="본문 내용",
            url="https://example.com/1",
            topic_domain="금융",
            matched_keywords=["금리", "CPI"],
            collected_at=datetime(2026, 4, 9, 3, 0, tzinfo=timezone.utc),
        )

        db = _TestSession()
        try:
            rows = db.query(CandidatePoolEntry).all()
            assert len(rows) == 1
            assert rows[0].title == "테스트 기사"
            assert json.loads(rows[0].matched_keywords_json) == ["금리", "CPI"]
        finally:
            db.close()

    def test_record_breaking_sent_persists_to_db(self):
        """record_breaking_sent → DB 에 기록됨."""
        from app.services.top5_briefing_service import record_breaking_sent

        record_breaking_sent(title="긴급 뉴스", topic_domain="금융")

        db = _TestSession()
        try:
            rows = db.query(BreakingSentKey).all()
            assert len(rows) == 1
        finally:
            db.close()

    def test_candidates_survive_restart_simulation(self):
        """기록 → 메모리 초기화 → DB 로드 → 후보 복원."""
        from app.services.top5_briefing_service import (
            _candidate_store,
            _reset_stores_for_tests,
            record_candidate,
            select_top5,
        )

        record_candidate(
            title="연준 금리 인상 CPI GDP 전망 분석",
            body="연준이 금리를 인상했다. GDP CPI 전망 분석 자금흐름. " * 20,
            url="https://example.com/1",
            topic_domain="금융",
            matched_keywords=["금리", "CPI", "GDP"],
            collected_at=datetime(2026, 4, 9, 3, 0, tzinfo=_KST).astimezone(timezone.utc),
        )

        assert len(_candidate_store) == 1

        # "재시작" 시뮬레이션
        _reset_stores_for_tests()
        assert len(_candidate_store) == 0

        # select_top5 호출 시 DB 에서 복원
        ref = datetime(2026, 4, 9, 5, 0, tzinfo=_KST)
        selected = select_top5(ref_kst=ref)
        # 복원 후 candidate_store 에 다시 들어가 있어야 함
        assert len(_candidate_store) >= 1

    def test_breaking_sent_survives_restart(self):
        """BREAKING_NOW 제외 키도 재시작 후 복원."""
        from app.services.top5_briefing_service import (
            _breaking_sent_keys,
            _reset_stores_for_tests,
            record_breaking_sent,
            record_candidate,
            select_top5,
        )

        record_candidate(
            title="연준 긴급 금리 인상",
            body="연준이 금리를 긴급 인상. GDP CPI 전망 분석 의미. " * 20,
            url="https://example.com/1",
            topic_domain="금융",
            matched_keywords=["금리"],
            collected_at=datetime(2026, 4, 9, 3, 0, tzinfo=_KST).astimezone(timezone.utc),
        )
        record_breaking_sent(title="연준 긴급 금리 인상", topic_domain="금융")

        # "재시작" 시뮬레이션
        _reset_stores_for_tests()
        assert len(_breaking_sent_keys) == 0

        # 복원 후 BREAKING_NOW 제외가 작동해야 함
        ref = datetime(2026, 4, 9, 5, 0, tzinfo=_KST)
        selected = select_top5(ref_kst=ref)
        assert len(selected) == 0  # BREAKING_NOW 제외

    def test_cleanup_after_briefing(self):
        """브리핑 후 DB 데이터 삭제."""
        from app.services.top5_briefing_service import (
            _cleanup_db_after_briefing,
            record_candidate,
        )

        record_candidate(
            title="테스트 기사",
            body="본문",
            url=None,
            topic_domain="금융",
            matched_keywords=["금리"],
            collected_at=datetime(2026, 4, 9, 3, 0, tzinfo=timezone.utc),
        )

        db = _TestSession()
        assert db.query(CandidatePoolEntry).count() == 1
        db.close()

        _cleanup_db_after_briefing()

        db = _TestSession()
        assert db.query(CandidatePoolEntry).count() == 0
        db.close()


# ---------------------------------------------------------------------------
# 모델 테이블 생성 테스트
# ---------------------------------------------------------------------------
class TestTableCreation:
    def test_all_tables_created(self):
        """3개 영속화 테이블이 생성되어야 함."""
        from sqlalchemy import inspect
        inspector = inspect(_test_engine)
        tables = inspector.get_table_names()
        assert "breaking_dedup_entries" in tables
        assert "candidate_pool_entries" in tables
        assert "breaking_sent_keys" in tables
