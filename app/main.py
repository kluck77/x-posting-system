"""
메인 애플리케이션 진입점
=========================
FastAPI 서버 + 텔레그램 봇을 동시에 실행합니다.
"""

import asyncio
import logging
import threading
from datetime import datetime, timedelta, timezone
import uvicorn
from app.config import settings, validate_settings
from app.db import init_db
from app.utils.logging_config import setup_logging

logger = logging.getLogger(__name__)

_KST = timezone(timedelta(hours=9))
_TOP5_HOUR = 5   # 05:00 KST
_TOP5_MINUTE = 0
_MONITOR_INTERVAL = 60  # 뉴스 모니터 폴링 간격 (초)
_CLEANUP_HOUR = 4  # 04:00 KST — Draft 자동 정리
_CLEANUP_MINUTE = 0


async def _top5_scheduler_loop() -> None:
    """매일 05:00 KST 에 run_top5_briefing() 을 실행하는 백그라운드 루프."""
    while True:
        now = datetime.now(tz=_KST)
        target = now.replace(hour=_TOP5_HOUR, minute=_TOP5_MINUTE, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        wait_seconds = (target - now).total_seconds()
        logger.info(
            f"[top5-scheduler] 다음 실행: {target.isoformat()} "
            f"(대기 {wait_seconds:.0f}초)"
        )
        await asyncio.sleep(wait_seconds)
        try:
            from app.services.top5_briefing_service import run_top5_briefing
            await run_top5_briefing()
        except Exception as e:
            logger.warning(f"[top5-scheduler] 실행 실패 (fail-open): {e}")


async def _news_monitor_loop() -> None:
    """1분 간격으로 news_monitor.run_monitor_cycle()을 실행하는 백그라운드 루프.

    - APScheduler 대체 (외부 패키지 불필요)
    - fail-open: 사이클 실패 시 로그만 남기고 다음 사이클 계속
    - news_monitor.py 가 서버에 없으면 자동 비활성화 (ImportError catch)
    """
    await asyncio.sleep(10)  # 초기화 완료 대기
    try:
        from app.services.news_monitor import run_monitor_cycle
    except ImportError:
        logger.info("[news-monitor] news_monitor.py 없음 — 폴링 비활성화")
        return
    while True:
        try:
            await run_monitor_cycle()
        except Exception as e:
            logger.warning(f"[news-monitor] 사이클 실패 (fail-open): {e}")
        await asyncio.sleep(_MONITOR_INTERVAL)


async def _draft_cleanup_loop() -> None:
    """매일 04:00 KST에 오래된 Draft를 정리하는 백그라운드 루프.

    정책: PENDING 7일, REJECTED 30일, FAILED 30일 경과 시 삭제.
    """
    while True:
        now = datetime.now(tz=_KST)
        target = now.replace(
            hour=_CLEANUP_HOUR, minute=_CLEANUP_MINUTE,
            second=0, microsecond=0,
        )
        if target <= now:
            target += timedelta(days=1)
        wait_seconds = (target - now).total_seconds()
        logger.info(
            f"[draft-cleanup] 다음 실행: {target.isoformat()} "
            f"(대기 {wait_seconds:.0f}초)"
        )
        await asyncio.sleep(wait_seconds)
        try:
            from app.db import SessionLocal
            from app.services.draft_service import DraftService
            db = SessionLocal()
            try:
                svc = DraftService(db)
                result = svc.cleanup_stale_drafts()
                logger.info(f"[draft-cleanup] 결과: {result}")
            finally:
                db.close()
        except Exception as e:
            logger.warning(f"[draft-cleanup] 실행 실패 (fail-open): {e}")


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

    # Top5 브리핑 스케줄러 (05:00 KST)
    asyncio.create_task(_top5_scheduler_loop())
    logger.info("[top5-scheduler] 05:00 KST 자동 실행 등록")

    # 뉴스 모니터 (1분 간격, 서버 전용 news_monitor.py 의존)
    asyncio.create_task(_news_monitor_loop())
    logger.info("[news-monitor] 1분 간격 폴링 등록")

    # Draft 자동 정리 (04:00 KST)
    asyncio.create_task(_draft_cleanup_loop())
    logger.info("[draft-cleanup] 04:00 KST 자동 정리 등록")

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
