"""
eval_store.py 테스트
=====================
PR 27 — SQLite 기반 eval 영속 저장소 검증.
"""

import sqlite3
import pytest

from app.services.eval_store import (
    save_eval_record,
    load_recent_records,
    cleanup_old_records,
    RETENTION_DAYS, RETENTION_MAX_ROWS,
    count_records,
    load_records_by_source,
    _ensure_table,
    _initialized_dbs,
)


@pytest.fixture
def db():
    """인메모리 SQLite 커넥션."""
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA journal_mode=WAL")
    yield conn
    _initialized_dbs.discard(id(conn))
    conn.close()


class TestEvalStore:
    """PR 27 — eval_store 영속 저장소."""

    def test_save_and_load(self, db):
        """저장 + 조회."""
        ok = save_eval_record(db, "eval_meta", {"mode": "VERIFY", "reward_type": "FOLLOW"})
        assert ok is True
        records = load_recent_records(db, "eval_meta")
        assert len(records) == 1
        assert records[0]["mode"] == "VERIFY"

    def test_count(self, db):
        """건수 조회."""
        save_eval_record(db, "eval_meta", {"a": 1})
        save_eval_record(db, "eval_meta", {"a": 2})
        save_eval_record(db, "gold_eval", {"b": 1})
        assert count_records(db, "eval_meta") == 2
        assert count_records(db, "gold_eval") == 1

    def test_load_recent_limit(self, db):
        """최근 N건 제한."""
        for i in range(10):
            save_eval_record(db, "eval_meta", {"idx": i})
        records = load_recent_records(db, "eval_meta", limit=3)
        assert len(records) == 3

    def test_load_by_source_id(self, db):
        """source_id 기반 조회."""
        save_eval_record(db, "pairwise_review", {"v": "A_BETTER"}, source_id="src_001")
        save_eval_record(db, "pairwise_review", {"v": "B_BETTER"}, source_id="src_002")
        save_eval_record(db, "eval_meta", {"m": "VERIFY"}, source_id="src_001")

        results = load_records_by_source(db, "src_001")
        assert len(results) == 2

        results_typed = load_records_by_source(db, "src_001", "pairwise_review")
        assert len(results_typed) == 1
        assert results_typed[0]["v"] == "A_BETTER"

    def test_empty_db(self, db):
        """빈 DB에서 조회 크래시 없음."""
        _ensure_table(db)
        assert load_recent_records(db, "eval_meta") == []
        assert count_records(db, "eval_meta") == 0

    def test_save_with_source_id(self, db):
        """source_id 저장 확인."""
        save_eval_record(db, "gold_eval", {"quality": "GOOD"}, source_id="src_123")
        results = load_records_by_source(db, "src_123", "gold_eval")
        assert len(results) == 1
        assert results[0]["quality"] == "GOOD"

    def test_multiple_record_types(self, db):
        """여러 record_type 독립 저장."""
        save_eval_record(db, "eval_meta", {"a": 1})
        save_eval_record(db, "gold_eval", {"b": 2})
        save_eval_record(db, "pairwise_review", {"c": 3})
        save_eval_record(db, "learning_record", {"d": 4})
        save_eval_record(db, "online_summary", {"e": 5})
        assert count_records(db, "eval_meta") == 1
        assert count_records(db, "gold_eval") == 1
        assert count_records(db, "pairwise_review") == 1
        assert count_records(db, "learning_record") == 1
        assert count_records(db, "online_summary") == 1


class TestRetention:
    """PR 31 — eval_records retention/cleanup."""

    def test_cleanup_by_max_rows(self, db):
        """max_rows 초과 시 오래된 것부터 삭제."""
        for i in range(15):
            save_eval_record(db, "eval_meta", {"idx": i})
        assert count_records(db, "eval_meta") == 15
        deleted = cleanup_old_records(db, retention_days=9999, max_rows=10)
        assert deleted == 5
        assert count_records(db, "eval_meta") == 10

    def test_cleanup_by_age(self, db):
        """retention_days=0 → 전부 삭제."""
        save_eval_record(db, "eval_meta", {"a": 1})
        save_eval_record(db, "gold_eval", {"b": 2})
        deleted = cleanup_old_records(db, retention_days=0)
        assert deleted >= 2
        assert count_records(db, "eval_meta") == 0

    def test_cleanup_empty_db(self, db):
        """빈 DB cleanup 크래시 없음."""
        deleted = cleanup_old_records(db)
        assert deleted == 0

    def test_retention_constants(self):
        """기본 retention 상수 확인."""
        assert RETENTION_DAYS == 90
        assert RETENTION_MAX_ROWS == 10000


class TestTestingGuard:
    """PR 31 — TESTING 환경변수 guard."""

    def test_testing_env_set(self):
        """conftest.py가 TESTING=1 설정했는지."""
        import os
        assert os.environ.get("TESTING") == "1"
