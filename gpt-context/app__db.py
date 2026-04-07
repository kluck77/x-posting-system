# app/db.py
# init_db()에 run_schema_migrations() 호출을 추가해야 합니다.
# Base.metadata.create_all() 은 기존 테이블에 컬럼을 추가하지 않으므로
# PRAGMA table_info + ALTER TABLE 패턴이 필요합니다.

import logging
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker, Session
from app.config import settings

logger = logging.getLogger(__name__)

engine_kwargs = {}
if settings.database_url.startswith("sqlite"):
    engine_kwargs["connect_args"] = {"check_same_thread": False}

engine = create_engine(settings.database_url, echo=False, **engine_kwargs)

if settings.database_url.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Session:
    return SessionLocal()


def _get_existing_columns(conn, table_name: str) -> set:
    """PRAGMA table_info로 기존 컬럼명 집합 반환"""
    result = conn.execute(text(f"PRAGMA table_info({table_name})"))
    return {row[1] for row in result}  # row[1] = 컬럼명


def run_schema_migrations(engine_):
    """
    [TODO] 이 함수를 구현하고 init_db()에서 호출해야 합니다.
    nullable 컬럼 추가: PRAGMA table_info 로 존재 여부 확인 후 ALTER TABLE 실행
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
    ]
    with engine_.connect() as conn:
        existing_cols = _get_existing_columns(conn, "drafts")
        for m in migrations:
            if m["column"] not in existing_cols:
                try:
                    conn.execute(text(m["ddl"]))
                    conn.commit()
                    logger.info(f"[migration] 컬럼 추가: {m['column']}")
                except Exception as e:
                    logger.error(f"[migration] 오류: {m['column']} - {e}")
            else:
                logger.info(f"[migration] 이미 존재: {m['column']}")


def init_db():
    from app.models.content import Base
    Base.metadata.create_all(bind=engine)   # 새 테이블 생성
    run_schema_migrations(engine)            # [TODO] 기존 테이블 컬럼 추가
    logger.info("데이터베이스 테이블 초기화 완료")
