"""
데이터베이스 연결 및 세션 관리
==============================
SQLite 데이터베이스에 연결하고, 테이블을 생성하고, 세션을 관리합니다.
"""

import logging
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker, Session
from app.config import settings

logger = logging.getLogger(__name__)

# 데이터베이스 엔진 생성
# SQLite는 파일 하나로 동작하는 간단한 데이터베이스입니다
# check_same_thread=False: FastAPI 등에서 여러 스레드가 접근할 수 있게 함
engine_kwargs = {}
if settings.database_url.startswith("sqlite"):
    engine_kwargs["connect_args"] = {"check_same_thread": False}

engine = create_engine(
    settings.database_url,
    echo=False,  # True로 바꾸면 모든 SQL 쿼리가 로그에 출력됨 (디버깅용)
    **engine_kwargs,
)

# SQLite에서 외래키 제약조건 활성화
if settings.database_url.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

# 세션 팩토리 생성
# 세션 = 데이터베이스와 대화하는 창구
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Session:
    """
    데이터베이스 세션을 가져옵니다.
    사용 후 반드시 닫아야 합니다.

    사용법:
        db = get_db()
        try:
            # 데이터베이스 작업
            ...
        finally:
            db.close()
    """
    db = SessionLocal()
    return db


def _get_existing_columns(conn, table_name: str) -> set:
    """PRAGMA table_info로 기존 컬럼명 집합 반환."""
    result = conn.execute(text(f"PRAGMA table_info({table_name})"))
    return {row[1] for row in result}


def _run_schema_migrations():
    """
    기존 테이블에 누락된 컬럼을 안전하게 추가합니다.
    - Base.metadata.create_all()은 기존 테이블의 컬럼을 추가하지 않으므로
      PRAGMA table_info로 존재 여부 확인 후 ALTER TABLE 실행합니다.
    - nullable 컬럼만 추가 (SQLite ALTER TABLE 제약)
    """
    migrations = [
        {
            "table": "drafts",
            "column": "predicted_publish_at",
            "ddl": "ALTER TABLE drafts ADD COLUMN predicted_publish_at DATETIME",
        },
        {
            "table": "drafts",
            "column": "prediction_reasoning",
            "ddl": "ALTER TABLE drafts ADD COLUMN prediction_reasoning TEXT",
        },
        {
            "table": "drafts",
            "column": "community_warning",
            "ddl": "ALTER TABLE drafts ADD COLUMN community_warning TEXT",
        },
        {
            "table": "drafts",
            "column": "reply_to_tweet_id",
            "ddl": "ALTER TABLE drafts ADD COLUMN reply_to_tweet_id VARCHAR(50)",
        },
        # Phase 4: 성과 로깅 기반 필드
        {
            "table": "drafts",
            "column": "content_type",
            "ddl": "ALTER TABLE drafts ADD COLUMN content_type VARCHAR(50)",
        },
        {
            "table": "drafts",
            "column": "topic_tags",
            "ddl": "ALTER TABLE drafts ADD COLUMN topic_tags VARCHAR(500)",
        },
        {
            "table": "drafts",
            "column": "output_format",
            "ddl": "ALTER TABLE drafts ADD COLUMN output_format VARCHAR(20) DEFAULT 'single'",
        },
        {
            "table": "drafts",
            "column": "manual_notes",
            "ddl": "ALTER TABLE drafts ADD COLUMN manual_notes TEXT",
        },
        # Phase 5: 비즈니스 분류 + 수익화 메타데이터
        {
            "table": "drafts",
            "column": "business_tags",
            "ddl": "ALTER TABLE drafts ADD COLUMN business_tags VARCHAR(500)",
        },
        {
            "table": "drafts",
            "column": "cta_type",
            "ddl": "ALTER TABLE drafts ADD COLUMN cta_type VARCHAR(50)",
        },
        {
            "table": "drafts",
            "column": "monetization_score",
            "ddl": "ALTER TABLE drafts ADD COLUMN monetization_score INTEGER",
        },
        {
            "table": "drafts",
            "column": "asset_goal",
            "ddl": "ALTER TABLE drafts ADD COLUMN asset_goal VARCHAR(50)",
        },
        {
            "table": "drafts",
            "column": "premium_reason",
            "ddl": "ALTER TABLE drafts ADD COLUMN premium_reason TEXT",
        },
        {
            "table": "drafts",
            "column": "b2b_candidate",
            "ddl": "ALTER TABLE drafts ADD COLUMN b2b_candidate BOOLEAN DEFAULT 0",
        },
        {
            "table": "drafts",
            "column": "b2b_target_audience",
            "ddl": "ALTER TABLE drafts ADD COLUMN b2b_target_audience VARCHAR(200)",
        },
        {
            "table": "drafts",
            "column": "b2b_use_case",
            "ddl": "ALTER TABLE drafts ADD COLUMN b2b_use_case VARCHAR(200)",
        },
        # Phase 5-B2B: B2B 후보 파이프라인
        {
            "table": "drafts",
            "column": "b2b_note",
            "ddl": "ALTER TABLE drafts ADD COLUMN b2b_note TEXT",
        },
        {
            "table": "drafts",
            "column": "b2b_status",
            "ddl": "ALTER TABLE drafts ADD COLUMN b2b_status VARCHAR(20)",
        },
        {
            "table": "drafts",
            "column": "b2b_updated_at",
            "ddl": "ALTER TABLE drafts ADD COLUMN b2b_updated_at DATETIME",
        },
        # Phase 7: 이메일/리드자석 메타데이터
        {
            "table": "drafts",
            "column": "lead_asset_name",
            "ddl": "ALTER TABLE drafts ADD COLUMN lead_asset_name VARCHAR(200)",
        },
        {
            "table": "drafts",
            "column": "lead_asset_type",
            "ddl": "ALTER TABLE drafts ADD COLUMN lead_asset_type VARCHAR(50)",
        },
        {
            "table": "drafts",
            "column": "lead_asset_note",
            "ddl": "ALTER TABLE drafts ADD COLUMN lead_asset_note TEXT",
        },
        {
            "table": "drafts",
            "column": "email_bucket",
            "ddl": "ALTER TABLE drafts ADD COLUMN email_bucket VARCHAR(50)",
        },
        {
            "table": "drafts",
            "column": "email_goal",
            "ddl": "ALTER TABLE drafts ADD COLUMN email_goal VARCHAR(50)",
        },
        # Phase 5-3: 프리미엄 후보 파이프라인
        {
            "table": "drafts",
            "column": "premium_status",
            "ddl": "ALTER TABLE drafts ADD COLUMN premium_status VARCHAR(20)",
        },
        {
            "table": "drafts",
            "column": "premium_note",
            "ddl": "ALTER TABLE drafts ADD COLUMN premium_note TEXT",
        },
        {
            "table": "drafts",
            "column": "premium_updated_at",
            "ddl": "ALTER TABLE drafts ADD COLUMN premium_updated_at DATETIME",
        },
        {
            "table": "drafts",
            "column": "target_reader_type",
            "ddl": "ALTER TABLE drafts ADD COLUMN target_reader_type VARCHAR(100)",
        },
        # Brief Offer 메타데이터
        {
            "table": "drafts",
            "column": "brief_type",
            "ddl": "ALTER TABLE drafts ADD COLUMN brief_type VARCHAR(50)",
        },
        {
            "table": "drafts",
            "column": "brief_price_tier",
            "ddl": "ALTER TABLE drafts ADD COLUMN brief_price_tier VARCHAR(20)",
        },
        {
            "table": "drafts",
            "column": "brief_summary_note",
            "ddl": "ALTER TABLE drafts ADD COLUMN brief_summary_note TEXT",
        },
        # CTA 카피 연결
        {
            "table": "drafts",
            "column": "cta_copy_id",
            "ddl": "ALTER TABLE drafts ADD COLUMN cta_copy_id INTEGER",
        },
    ]
    with engine.connect() as conn:
        existing_cols = _get_existing_columns(conn, "drafts")
        for m in migrations:
            if m["column"] not in existing_cols:
                try:
                    conn.execute(text(m["ddl"]))
                    conn.commit()
                    logger.info(f"[migration] 컬럼 추가: {m['column']}")
                except Exception as e:
                    logger.error(f"[migration] 오류: {m['column']} — {e}")
            else:
                logger.debug(f"[migration] 이미 존재: {m['column']}")


def _ensure_eval_records_table():
    """
    PR 30 — eval_records 테이블 생성 (eval_store.py 용).
    ORM 모델 없이 raw DDL 로 관리. init_db() 시 자동 실행.
    """
    try:
        with engine.connect() as conn:
            conn.execute(text(
                "CREATE TABLE IF NOT EXISTS eval_records ("
                "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
                "  record_type TEXT NOT NULL,"
                "  source_id TEXT DEFAULT '',"
                "  payload TEXT NOT NULL,"
                "  created_at TEXT NOT NULL"
                ")"
            ))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_eval_type_created "
                "ON eval_records (record_type, created_at)"
            ))
            conn.commit()
            logger.info("[migration] eval_records 테이블 확인 완료")
    except Exception as e:
        logger.warning(f"[migration] eval_records 생성 실패 (무시): {e}")


def init_db():
    """
    데이터베이스 테이블을 생성합니다.
    앱 시작 시 한 번 호출됩니다.
    이미 존재하는 테이블은 건너뜁니다.
    """
    from app.models.content import Base  # 순환 import 방지
    import app.models.dedup  # noqa: F401 — 테이블 등록 (dedup + candidate pool)
    Base.metadata.create_all(bind=engine)
    _run_schema_migrations()
    _ensure_eval_records_table()  # PR 30
    _cleanup_eval_records()  # PR 31
    logger.info("데이터베이스 테이블 초기화 완료")


def _cleanup_eval_records():
    """PR 31 — 앱 시작 시 eval_records 오래된 레코드 정리. fail-open."""
    try:
        db = get_db()
        from app.services.eval_store import cleanup_old_records
        deleted = cleanup_old_records(db)
        if deleted > 0:
            logger.info(f"[startup] eval_records cleanup: {deleted}건 삭제")
        db.close()
    except Exception as e:
        logger.warning(f"[startup] eval_records cleanup 실패 (무시): {e}")
