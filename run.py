"""
실행 스크립트
=============
프로젝트 루트에서 이 파일을 실행하면 전체 시스템이 시작됩니다.

사용법:
    python run.py

이 명령 하나로:
1. 데이터베이스 초기화
2. FastAPI 서버 시작 (http://localhost:8000)
3. 텔레그램 봇 시작 (설정되어 있으면)
"""

import sys
import os

# 프로젝트 루트를 Python 경로에 추가
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.main import main

if __name__ == "__main__":
    main()
