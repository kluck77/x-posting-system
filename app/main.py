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
from app.services.growth.ring_dispatcher import ring_a_loop, ring_c_loop
from app.services.growth.comment_hunter_cycle import (
    comment_hunter_cycle, make_hunter_runner, set_runner_mode,
)
from app.services.growth.post_queue import get_post_queue

logger = logging.getLogger(__name__)

_KST = timezone(timedelta(hours=9))
_MONITOR_INTERVAL = 60  # 뉴스 모니터 폴링 간격 (초)
_CLEANUP_HOUR = 4  # 04:00 KST — Draft 자동 정리
_CLEANUP_MINUTE = 0
_DIGEST_HOUR = 5    # 05:00 KST — 모닝 다이제스트 (공식 5AM 브리핑)
_DIGEST_MINUTE = 0


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


async def _competitor_monitor_loop() -> None:
    """6시간 주기 경쟁자 Nitter RSS 수집. fail-open.

    psych_enabled=False 이면 비활성화. 첫 주기는 120초 후.
    """
    from app.config import settings
    await asyncio.sleep(120)
    try:
        from app.sources.competitor_monitor import collect_all, save_to_db
    except ImportError:
        logger.info("[competitor-monitor] 모듈 없음 — 비활성")
        return
    while True:
        if not getattr(settings, "psych_enabled", True):
            await asyncio.sleep(3600)
            continue
        try:
            posts = await collect_all()
            if posts:
                save_to_db(posts)
                logger.info(f"[competitor-monitor] {len(posts)}개 수집 저장")
        except Exception as e:
            logger.warning(f"[competitor-monitor] 실패: {e}")
        await asyncio.sleep(6 * 3600)


async def _polymarket_fetch_loop() -> None:
    """30분 주기 폴리마켓 Gamma API 수집 + SQLite 저장 + intel_items 적재.

    psych_enabled=False 면 대기. 첫 주기 90초 후.
    upsert_to_intel 은 55점 이상인 시장만 대시보드 shortlist 에 등록.
    """
    from app.config import settings
    await asyncio.sleep(90)
    try:
        from app.sources.polymarket_fetcher import (
            fetch_with_retry, save_to_db, upsert_to_intel,
        )
    except ImportError:
        logger.info("[polymarket-fetch] 모듈 없음 — 비활성")
        return
    while True:
        if not getattr(settings, "psych_enabled", True):
            await asyncio.sleep(1800)
            continue
        try:
            items = await fetch_with_retry(limit=100)
            if items:
                save_to_db(items)
                intel_count = upsert_to_intel(items)
                logger.info(
                    f"[polymarket-fetch] 수집 {len(items)}개 → "
                    f"intel 신규 {intel_count}개"
                )
        except Exception as e:
            logger.warning(f"[polymarket-fetch] 실패: {e}")
        await asyncio.sleep(30 * 60)


async def _kor_community_trending_loop() -> None:
    """15분 주기 한국 커뮤니티 트렌딩 수집. fail-open.

    제목만 캐시, DB 저장 없음. 본문·로그인 금지 원칙 준수.
    """
    from app.config import settings
    await asyncio.sleep(60)
    try:
        from app.sources.korean_community_trending import get_trending
    except ImportError:
        logger.info("[kor-community-trending] 모듈 없음 — 비활성")
        return
    while True:
        if not getattr(settings, "psych_enabled", True):
            await asyncio.sleep(900)
            continue
        try:
            await get_trending()
        except Exception as e:
            logger.warning(f"[kor-community-trending] 실패: {e}")
        await asyncio.sleep(15 * 60)


async def _feedback_loop() -> None:
    """매주 일요일 23:00 KST 룰 가중치 재계산."""
    try:
        from zoneinfo import ZoneInfo
        from datetime import datetime, timedelta
        KST = ZoneInfo("Asia/Seoul")
    except Exception as e:
        logger.warning(f"[feedback-loop] 시간대 모듈 실패: {e}")
        return
    while True:
        try:
            now = datetime.now(KST)
            days_until_sun = (6 - now.weekday()) % 7
            if days_until_sun == 0 and now.hour >= 23:
                days_until_sun = 7
            target = (
                now.replace(hour=23, minute=0, second=0, microsecond=0)
                + timedelta(days=days_until_sun)
            )
            wait = (target - now).total_seconds()
            if wait > 0:
                await asyncio.sleep(wait)
            try:
                from app.services.feedback_loop import reweight_rules
                reweight_rules()
            except Exception as e:
                logger.warning(f"[feedback-loop] reweight 실패: {e}")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning(f"[feedback-loop] 루프 오류: {e}")
            await asyncio.sleep(3600)


# Quality 95 — 경쟁계정 핸들 (X API 가용 핸들만)
COMPETITOR_HANDLES = [
    "coinness_kr",
    "CoinKor",
    "coinboy717",
]


async def _competitor_benchmark_loop() -> None:
    """매일 03:00 KST 경쟁계정 30일 평균 ER 갱신."""
    try:
        from zoneinfo import ZoneInfo
        from datetime import datetime, timedelta
        KST = ZoneInfo("Asia/Seoul")
    except Exception as e:
        logger.warning(f"[competitor-benchmark] 시간대 모듈 실패: {e}")
        return
    while True:
        try:
            now = datetime.now(KST)
            target = now.replace(hour=3, minute=0, second=0, microsecond=0)
            if now >= target:
                target += timedelta(days=1)
            wait = (target - now).total_seconds()
            if wait > 0:
                await asyncio.sleep(wait)
            try:
                from app.services.er_collector import benchmark_competitor
                for handle in COMPETITOR_HANDLES:
                    await benchmark_competitor(handle)
                    await asyncio.sleep(2)  # rate limit 방지
            except Exception as e:
                logger.warning(f"[competitor-benchmark] 실행 실패: {e}")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning(f"[competitor-benchmark] 루프 오류: {e}")
            await asyncio.sleep(3600)


async def _morning_digest_loop() -> None:
    """매일 05:01 KST 에 run_morning_digest() 를 실행하는 백그라운드 루프.

    news_monitor 가 22:00~05:00 수집한 overnight_buffer 기반.
    morning_digest.py 가 없으면 자동 비활성화.
    """
    try:
        from app.services.morning_digest import run_morning_digest
    except ImportError:
        logger.info("[morning-digest] morning_digest.py 없음 — 비활성화")
        return
    while True:
        now = datetime.now(tz=_KST)
        target = now.replace(
            hour=_DIGEST_HOUR, minute=_DIGEST_MINUTE,
            second=0, microsecond=0,
        )
        if target <= now:
            target += timedelta(days=1)
        wait_seconds = (target - now).total_seconds()
        logger.info(
            f"[morning-digest] 다음 실행: {target.isoformat()} "
            f"(대기 {wait_seconds:.0f}초)"
        )
        await asyncio.sleep(wait_seconds)
        try:
            await run_morning_digest()
        except Exception as e:
            logger.warning(f"[morning-digest] 실행 실패 (fail-open): {e}")


# ── Ring / CommentHunter connector ────────────────────────────────────
# Ring A : post_queue 연결 (real)
# Ring C : Breaking 큐 없음 — orchestrator Step 1.6 이 즉시 처리 (stub 유지)
# Hunter : CommentHunter + tg_send 래퍼 (real, async builder)

# Ring A — post_queue 연결 (모듈 레벨 싱글턴)
_post_queue = get_post_queue()


async def _ring_a_send_next_card() -> bool:
    """대기 중 draft 1개 꺼내 텔레그램 승인 카드 전송."""
    try:
        pending = _post_queue.list_pending()
        if not pending:
            return False
        post = pending[0]
        await _post_queue._send_approval_notification(post)
        return True
    except Exception as e:
        logger.warning(f"[Ring A] 전송 실패 (무시): {e}")
        return False


def _ring_a_pending_count() -> int:
    """대기 중 draft 수."""
    try:
        return _post_queue.count_pending()
    except Exception:
        return 0


# Ring C — stub 유지 (Breaking 은 orchestrator Step 1.6 에서 즉시 처리)
async def _ring_c_send_breaking_card_stub() -> bool:
    logger.debug("[Ring C][stub] Breaking 큐 없음 — skip")
    return False


def _ring_c_breaking_pending_stub() -> int:
    return 0


# Comment Hunter — 실 연결 (async 팩토리)
# spec 의 telegram_service.send_message 는 미존재 → 실제 동등 함수
# growth/_tg_helper.tg_send (async fn(text, parse_mode, disable_preview) -> bool) 사용.
async def _build_hunter_runner():
    try:
        from app.services.growth._tg_helper import tg_send

        async def _send(text: str) -> None:
            await tg_send(text)

        runner = await make_hunter_runner(_send)
        set_runner_mode("real", "")
        return runner
    except Exception as e:
        logger.warning(f"[Hunter] runner 초기화 실패 (noop fallback): {e}")
        set_runner_mode("noop", str(e))

        async def _noop() -> int:
            return 0

        return _noop


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

    # 뉴스 모니터 (1분 간격, 서버 전용 news_monitor.py 의존)
    asyncio.create_task(_news_monitor_loop())
    logger.info("[news-monitor] 1분 간격 폴링 등록")

    # 5AM 모닝 다이제스트 (overnight_buffer 기반, 공식 브리핑 경로)
    asyncio.create_task(_morning_digest_loop())
    logger.info("[morning-digest] 05:00 KST 자동 실행 등록")

    # Draft 자동 정리 (04:00 KST)
    asyncio.create_task(_draft_cleanup_loop())
    logger.info("[draft-cleanup] 04:00 KST 자동 정리 등록")

    # Phase 3 psych: 경쟁자 모니터 (6시간 주기) + 한국 커뮤니티 트렌딩 (15분)
    asyncio.create_task(_competitor_monitor_loop(), name="competitor_monitor")
    logger.info("[competitor-monitor] 6시간 주기 Nitter RSS 수집 등록")
    asyncio.create_task(_kor_community_trending_loop(), name="kor_community_trending")
    logger.info("[kor-community-trending] 15분 주기 등록")
    asyncio.create_task(_polymarket_fetch_loop(), name="polymarket_fetch")
    logger.info("[polymarket-fetch] 30분 주기 Gamma API 수집 등록")

    # Ops 자동화 — post_performance 측정 루프 (5분 주기 1h/6h/24h ER 측정)
    try:
        from app.services.post_performance import measure_loop as _perf_loop
        asyncio.create_task(_perf_loop(), name="post_performance_measure")
        logger.info("[post-performance] 5분 주기 ER 측정 루프 등록")
    except Exception as e:
        logger.warning(f"[post-performance] 등록 실패 (무시): {e}")

    # Ops 자동화 — 매일 06:00 KST 5-AI 헬스 리포트
    try:
        from app.services.pipeline_health import daily_report_loop as _health_loop
        asyncio.create_task(_health_loop(), name="pipeline_health_daily")
        logger.info("[pipeline-health] 매일 06:00 KST 헬스 리포트 등록")
    except Exception as e:
        logger.warning(f"[pipeline-health] 등록 실패 (무시): {e}")

    # Quality 95 — 매주 일요일 23:00 KST 룰 가중치 재계산
    try:
        asyncio.create_task(_feedback_loop(), name="feedback_loop_weekly")
        logger.info("[feedback-loop] 매주 일요일 23:00 KST 룰 재가중치 등록")
    except Exception as e:
        logger.warning(f"[feedback-loop] 등록 실패 (무시): {e}")

    # Quality 95 — 매일 03:00 KST 경쟁계정 벤치마크
    try:
        asyncio.create_task(
            _competitor_benchmark_loop(), name="competitor_benchmark_daily",
        )
        logger.info("[competitor-benchmark] 매일 03:00 KST 등록")
    except Exception as e:
        logger.warning(f"[competitor-benchmark] 등록 실패 (무시): {e}")

    # Ring A — 최적 시각 텔레그램 카드 전송 (07:30/12:00/18:30/22:30 KST)
    asyncio.create_task(
        ring_a_loop(_ring_a_send_next_card, _ring_a_pending_count),
        name="ring_a",
    )
    logger.info("[ring-a] 슬롯 기반 카드 전송 등록 (post_queue 연결)")

    # Ring C — Breaking priority=0 즉시 전송 (stub: orchestrator Step 1.6 처리)
    asyncio.create_task(
        ring_c_loop(_ring_c_send_breaking_card_stub, _ring_c_breaking_pending_stub),
        name="ring_c",
    )
    logger.info("[ring-c] Breaking 즉시 전송 등록 (stub — Step 1.6 보완용)")

    # Comment Hunter — 대형 계정 리플 사이클 (팔로워 확보 전까지 off)
    # .env 에서 COMMENT_HUNTER_ENABLED=true 주면 재활성화.
    if settings.comment_hunter_enabled:
        _hunter_runner = await _build_hunter_runner()
        asyncio.create_task(
            comment_hunter_cycle(_hunter_runner),
            name="comment_hunter",
        )
        logger.info("[comment-hunter] 30분 주기 사이클 등록 (CommentHunter + tg_send)")
    else:
        logger.info("[comment-hunter] 비활성 — COMMENT_HUNTER_ENABLED=true 설정 시 활성화")

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
