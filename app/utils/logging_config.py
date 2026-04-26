"""
로깅 설정
=========
앱 전체에서 사용하는 로깅을 설정합니다.
초보자도 읽기 쉬운 로그 형식을 사용합니다.
"""

import logging
import sys
from app.config import settings


def setup_logging():
    """
    로깅을 설정합니다.
    로그는 터미널(콘솔)에 출력됩니다.
    """
    log_level = getattr(logging, settings.log_level.upper(), logging.INFO)

    # 로그 형식: [시간] [레벨] [모듈] 메시지
    log_format = "[%(asctime)s] [%(levelname)-7s] [%(name)-25s] %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"

    # 기본 로거 설정
    logging.basicConfig(
        level=log_level,
        format=log_format,
        datefmt=date_format,
        handlers=[
            logging.StreamHandler(sys.stderr),
        ],
    )

    # 외부 라이브러리 로그 레벨 조정 (너무 시끄러운 것 줄이기)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("uvicorn").setLevel(logging.INFO)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

    logger = logging.getLogger(__name__)
    logger.info(f"로깅 설정 완료: 레벨={settings.log_level}")
