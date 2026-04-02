"""
메인 애플리케이션 진입점
=========================
FastAPI 서버 + 텔레그램 봇을 동시에 실행합니다.
"""

import asyncio
import logging
import threading
import uvicorn
from app.config import settings, validate_settings
from app.db import init_db
from app.utils.logging_config import setup_logging

logger = logging.getLogger(__name__)


def _start_news_monitor():
    """APScheduler로 뉴스 모니터 + 모닝 다이제스트를 백그라운드에서 시작합니다."""
    if not settings.monitor_enabled:
        logger.info("뉴스 모니터 비활성 (MONITOR_ENABLED=false)")
        return

    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from apscheduler.triggers.cron import CronTrigger
        from app.services.news_monitor import run_monitor_cycle
        from app.services.morning_digest import run_morning_digest

        scheduler = AsyncIOScheduler()

        # 1분 간격 속보 모니터
        scheduler.add_job(
            run_monitor_cycle,
            "interval",
            minutes=settings.monitor_interval_minutes,
            id="news_monitor",
            max_instances=1,
            coalesce=True,
        )

        # 오전 5시 KST (= 20:00 UTC) 모닝 다이제스트
        if settings.digest_enabled:
            digest_utc_hour = (settings.digest_hour_kst - 9) % 24
            scheduler.add_job(
                run_morning_digest,
                CronTrigger(hour=digest_utc_hour, minute=0, timezone="UTC"),
                id="morning_digest",
                max_instances=1,
                coalesce=True,
            )
            logger.info(
                f"✓ 모닝 다이제스트 예약: 오전 {settings.digest_hour_kst}시 KST "
                f"(UTC {digest_utc_hour:02d}:00)"
            )

        scheduler.start()
        logger.info(
            f"✓ 뉴스 모니터 시작: {settings.monitor_interval_minutes}분 간격, "
            f"교차 확인 최소 {settings.cross_verify_min_sources}개 출처, "
            f"최대 {settings.monitor_max_alerts_per_run}건/사이클"
        )
        return scheduler
    except ImportError:
        logger.warning("apscheduler 미설치 — 뉴스 모니터 비활성. pip install apscheduler")
        return None
    except Exception as e:
        logger.error(f"뉴스 모니터 시작 실패: {e}")
        return None


def run_fastapi_server():
    """FastAPI 서버를 실행합니다."""
    uvicorn.run(
        "app.api.admin:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        log_level=settings.log_level.lower(),
    )


async def run_all():
    """FastAPI + 텔레그램 봇을 동시에 실행합니다."""
    # 로깅 설정
    setup_logging()

    # 설정 검증
    logger.info("=" * 50)
    logger.info("X Posting System 시작")
    logger.info("=" * 50)

    warnings = validate_settings(settings)
    for w in warnings:
        logger.warning(w)

    ai_status = settings.ai_status_summary()
    logger.info(f"AI 프로바이더 상태: {ai_status}")

    # 데이터베이스 초기화
    init_db()
    logger.info("데이터베이스 초기화 완료")

    # FastAPI를 별도 스레드에서 실행
    api_thread = threading.Thread(target=run_fastapi_server, daemon=True)
    api_thread.start()
    logger.info("FastAPI 서버 시작: http://localhost:8000")
    logger.info("API 문서: http://localhost:8000/docs")

    # 뉴스 모니터 시작 (APScheduler — asyncio 이벤트 루프에서 실행)
    _start_news_monitor()

    # 텔레그램 봇 실행
    if settings.has_telegram_config:
        from app.telegram_bot import run_telegram_bot
        logger.info("텔레그램 봇 시작...")
        await run_telegram_bot()
    else:
        logger.info("텔레그램 미설정. API 전용 모드로 실행합니다.")
        logger.info("http://localhost:8000/docs 에서 수동으로 사용하세요.")
        # 텔레그램 없이 API만 실행
        try:
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            logger.info("시스템 종료")


def main():
    """메인 진입점"""
    asyncio.run(run_all())


if __name__ == "__main__":
    main()
