"""
데이터베이스 초기화 스크립트
==============================
테이블을 생성합니다. 이미 존재하는 테이블은 건너뜁니다.

사용법:
    python scripts/init_db.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db import init_db


def main():
    print("🗄️ 데이터베이스 초기화 중...")
    init_db()
    print("✅ 데이터베이스 초기화 완료!")
    print("   파일 위치: x_poster.db (프로젝트 루트)")


if __name__ == "__main__":
    main()
