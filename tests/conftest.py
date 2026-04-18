"""
테스트 공통 설정
================
모든 테스트에서 공유하는 fixtures를 정의합니다.
"""

import os
import sys
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# PR 31: 테스트 환경에서 get_db() 자동 획득 방지
os.environ["TESTING"] = "1"

# 프로젝트 루트를 경로에 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.models.content import Base


@pytest.fixture
def db_session():
    """
    테스트용 인메모리 SQLite 세션.
    각 테스트마다 새로운 빈 DB를 만듭니다.
    """
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    engine.dispose()
