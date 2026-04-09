"""
데이터베이스 연결 및 세션 관리
==============================
SQLite 데이터베이스에 연결하고, 테이블을 생성하고, 세션을 관리합니다.
"""

import logging
from sqlalchemy import create_engine, event
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


def init_db():
    """
    데이터베이스 테이블을 생성합니다.
    앱 시작 시 한 번 호출됩니다.
    이미 존재하는 테이블은 건너뜁니다.
    """
    from app.models.content import Base  # 순환 import 방지
    import app.models.dedup  # noqa: F401 — 테이블 등록 (dedup + candidate pool)
    Base.metadata.create_all(bind=engine)
    logger.info("데이터베이스 테이블 초기화 완료")
