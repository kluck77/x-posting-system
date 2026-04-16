"""
평가 데이터 영속 저장소
========================
PR 27 — eval_meta / gold_eval / pairwise_review / online_eval 버퍼를
SQLite 에 영속 저장한다. 재시작 후에도 보존.

설계:
- 기존 app/db.py 의 engine 재사용 (별도 DB 파일 아님)
- 테이블 자동 생성 (CREATE IF NOT EXISTS)
- 모든 레코드를 JSON text 로 저장 (스키마 변경 없이 확장 가능)
- fail-open: 저장 실패 시 경고만 남기고 파이프라인 계속

테이블:
  eval_records — record_type + JSON payload + created_at
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)


def _get_raw_conn(db):
    """SQLAlchemy Session → raw sqlite3 connection 추출. raw면 그대로."""
    try:
        # SQLAlchemy Session
        raw = db.connection().connection
        return raw
    except (AttributeError, Exception):
        return db

# ── 테이블 DDL ──
_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS eval_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    record_type TEXT NOT NULL,
    source_id TEXT DEFAULT '',
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL
)
"""

_CREATE_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_eval_type_created
ON eval_records (record_type, created_at)
"""

_initialized_dbs: set = set()


def _ensure_table(db) -> None:
    """테이블 + 인덱스 자동 생성. 커넥션별 1회."""
    db_id = id(db)
    if db_id in _initialized_dbs:
        return
    try:
        raw = _get_raw_conn(db)
        raw.execute(_CREATE_TABLE_SQL)
        raw.execute(_CREATE_INDEX_SQL)
        raw.commit()
        _initialized_dbs.add(db_id)
    except Exception as e:
        logger.warning(f"[EvalStore] 테이블 생성 실패 (무시): {e}")
        _initialized_dbs.add(db_id)  # 재시도 방지


def save_eval_record(
    db,
    record_type: str,
    payload: dict,
    source_id: str = "",
) -> bool:
    """
    eval 레코드 1건 저장.

    record_type: "eval_meta" | "gold_eval" | "pairwise_review" |
                 "learning_record" | "online_summary"
    payload: dict (JSON 직렬화)
    source_id: 소스 식별자 (pairwise 비교 시 동일 소스 보장용)

    반환: 저장 성공 여부 (fail-open)
    """
    _ensure_table(db)
    try:
        raw = _get_raw_conn(db)
        now = datetime.now(timezone.utc).isoformat()
        raw.execute(
            "INSERT INTO eval_records (record_type, source_id, payload, created_at) "
            "VALUES (?, ?, ?, ?)",
            (record_type, source_id, json.dumps(payload, ensure_ascii=False), now),
        )
        raw.commit()
        return True
    except Exception as e:
        logger.warning(f"[EvalStore] 저장 실패 (무시): {e}")
        return False


def load_recent_records(
    db,
    record_type: str,
    limit: int = 100,
) -> list[dict]:
    """
    최근 N건 레코드 조회 (최신순).

    반환: payload dict 리스트 (파싱 실패 시 스킵)
    """
    _ensure_table(db)
    try:
        raw = _get_raw_conn(db)
        rows = raw.execute(
            "SELECT payload FROM eval_records "
            "WHERE record_type = ? "
            "ORDER BY created_at DESC LIMIT ?",
            (record_type, limit),
        ).fetchall()
        results = []
        for (raw,) in rows:
            try:
                results.append(json.loads(raw))
            except (json.JSONDecodeError, TypeError):
                continue
        return results
    except Exception as e:
        logger.warning(f"[EvalStore] 조회 실패 (무시): {e}")
        return []


def count_records(
    db,
    record_type: str,
) -> int:
    """record_type 별 총 건수."""
    _ensure_table(db)
    try:
        raw = _get_raw_conn(db)
        row = raw.execute(
            "SELECT COUNT(*) FROM eval_records WHERE record_type = ?",
            (record_type,),
        ).fetchone()
        return row[0] if row else 0
    except Exception as e:
        logger.warning(f"[EvalStore] 카운트 실패 (무시): {e}")
        return 0


def load_records_by_source(
    db,
    source_id: str,
    record_type: Optional[str] = None,
) -> list[dict]:
    """
    source_id 로 레코드 조회 (pairwise 비교용).

    record_type 지정 시 해당 타입만 필터.
    """
    _ensure_table(db)
    try:
        conn = _get_raw_conn(db)
        if record_type:
            rows = conn.execute(
                "SELECT payload FROM eval_records "
                "WHERE source_id = ? AND record_type = ? "
                "ORDER BY created_at DESC",
                (source_id, record_type),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT payload FROM eval_records "
                "WHERE source_id = ? "
                "ORDER BY created_at DESC",
                (source_id,),
            ).fetchall()
        results = []
        for (payload_str,) in rows:
            try:
                results.append(json.loads(payload_str))
            except (json.JSONDecodeError, TypeError):
                continue
        return results
    except Exception as e:
        logger.warning(f"[EvalStore] source 조회 실패 (무시): {e}")
        return []
