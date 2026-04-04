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


def _start_schedulers():
    """APScheduler로 뉴스 모니터 + Growth 파이프라인을 백그라운드에서 시작합니다."""
    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from apscheduler.triggers.cron import CronTrigger

        scheduler = AsyncIOScheduler()

        # ── 뉴스 모니터 ────────────────────────────────────────────────────────
        if settings.monitor_enabled:
            from app.services.news_monitor import run_monitor_cycle
            from app.services.morning_digest import run_morning_digest

            scheduler.add_job(
                run_monitor_cycle,
                "interval",
                minutes=settings.monitor_interval_minutes,
                id="news_monitor",
                max_instances=1,
                coalesce=True,
            )
            logger.info(
                f"✓ 뉴스 모니터: {settings.monitor_interval_minutes}분 간격, "
                f"교차확인 ≥{settings.cross_verify_min_sources}개, "
                f"최대 {settings.monitor_max_alerts_per_run}건/사이클"
            )

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
                    f"✓ 모닝 다이제스트: 오전 {settings.digest_hour_kst}시 KST "
                    f"(UTC {digest_utc_hour:02d}:00)"
                )
        else:
            logger.info("뉴스 모니터 비활성 (MONITOR_ENABLED=false)")

        # ── Growth 파이프라인 ───────────────────────────────────────────────────
        try:
            from app.services.growth.post_queue import run_queue_scheduler
            from app.services.growth.reply_monitor import run_reply_monitor
            from app.services.growth.weekly_report import run_weekly_report

            # 게시 큐 스케줄러 — 5분마다 최적 슬롯 체크
            scheduler.add_job(
                run_queue_scheduler,
                "interval",
                minutes=5,
                id="post_queue",
                max_instances=1,
                coalesce=True,
            )

            # 멘션 모니터 — 5분마다 새 답글 체크
            scheduler.add_job(
                run_reply_monitor,
                "interval",
                minutes=5,
                id="reply_monitor",
                max_instances=1,
                coalesce=True,
            )

            # 주간 성과 리포트 — 매주 월요일 오전 9시 KST (= 00:00 UTC)
            scheduler.add_job(
                run_weekly_report,
                CronTrigger(day_of_week="mon", hour=0, minute=0, timezone="UTC"),
                id="weekly_report",
                max_instances=1,
                coalesce=True,
            )

            logger.info("✓ Growth 파이프라인: 게시큐(5분), 멘션모니터(5분), 주간리포트(월 09:00 KST)")
        except Exception as e:
            logger.warning(f"Growth 파이프라인 스케줄러 등록 실패 (무시): {e}")

        scheduler.start()
        return scheduler

    except ImportError:
        logger.warning("apscheduler 미설치 — 스케줄러 비활성. pip install apscheduler")
        return None
    except Exception as e:
        logger.error(f"스케줄러 시작 실패: {e}")
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

    # 스케줄러 시작 (뉴스 모니터 + Growth 파이프라인)
    _start_schedulers()

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
