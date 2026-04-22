"""Comment Hunter Cycle — 대형 계정 리플 자동 사이클.

comment_hunter.py 의 기존 로직을 주기적으로 실행.
리플 초안이 생성되면 텔레그램 승인 요청. 자동 발행 없음.

주기: 60초마다 폴링
하루 최대 리플 승인 요청: 25개
계정당 하루 최대: 1개
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))
CYCLE_INTERVAL_SEC = 60
DAILY_REPLY_CAP = 25
PER_ACCOUNT_DAILY_CAP = 1


async def comment_hunter_cycle(run_hunter_fn) -> None:
    """Comment Hunter 주기 실행 루프.

    Args:
        run_hunter_fn: async fn() -> int
            comment_hunter 1회 실행.
            생성된 리플 초안 수 반환.
    """
    daily_count = 0
    last_reset_date = datetime.now(KST).date()

    while True:
        try:
            today = datetime.now(KST).date()
            if today != last_reset_date:
                daily_count = 0
                last_reset_date = today

            if daily_count >= DAILY_REPLY_CAP:
                logger.info(f"[CommentHunter] 일일 한도 도달 ({DAILY_REPLY_CAP}). 대기.")
                await asyncio.sleep(CYCLE_INTERVAL_SEC * 10)
                continue

            new_drafts = await run_hunter_fn()
            if new_drafts > 0:
                daily_count += new_drafts
                logger.info(
                    f"[CommentHunter] 리플 초안 {new_drafts}개 생성. "
                    f"오늘 {daily_count}/{DAILY_REPLY_CAP}"
                )

            await asyncio.sleep(CYCLE_INTERVAL_SEC)

        except asyncio.CancelledError:
            logger.info("[CommentHunter] 루프 종료")
            break
        except Exception as e:
            logger.warning(f"[CommentHunter] 오류 (무시): {e}")
            await asyncio.sleep(CYCLE_INTERVAL_SEC)
