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
CYCLE_INTERVAL_SEC = 1800     # 30분 — Grok live search 비용 절감 (월 7.2k 호출)
DAILY_REPLY_CAP = 25
PER_ACCOUNT_DAILY_CAP = 1


# ── 모듈 레벨 상태 — 대시보드 scheduler-status 에서 읽음 ───────────────
_hunter_state: dict = {
    "last_polled_at": None,      # datetime (KST-aware) or None
    "today_count": 0,
    "last_reset_date": None,
    "runner_mode": "unset",      # "unset" | "real" | "noop"
    "reason": "",                # noop 사유
}


def get_hunter_state() -> dict:
    return dict(_hunter_state)


def set_runner_mode(mode: str, reason: str = "") -> None:
    """main.py 가 runner 빌드 결과를 기록할 때 호출."""
    _hunter_state["runner_mode"] = mode
    _hunter_state["reason"] = reason


async def comment_hunter_cycle(run_hunter_fn) -> None:
    """Comment Hunter 주기 실행 루프.

    Args:
        run_hunter_fn: async fn() -> int
            comment_hunter 1회 실행.
            생성된 리플 초안 수 반환.
    """
    daily_count = 0
    last_reset_date = datetime.now(KST).date()
    _hunter_state["today_count"] = 0
    _hunter_state["last_reset_date"] = last_reset_date.isoformat()

    while True:
        try:
            today = datetime.now(KST).date()
            if today != last_reset_date:
                daily_count = 0
                last_reset_date = today
                _hunter_state["today_count"] = 0
                _hunter_state["last_reset_date"] = last_reset_date.isoformat()

            if daily_count >= DAILY_REPLY_CAP:
                logger.info(f"[CommentHunter] 일일 한도 도달 ({DAILY_REPLY_CAP}). 대기.")
                await asyncio.sleep(CYCLE_INTERVAL_SEC * 10)
                continue

            new_drafts = await run_hunter_fn()
            _hunter_state["last_polled_at"] = datetime.now(KST)
            if new_drafts > 0:
                daily_count += new_drafts
                _hunter_state["today_count"] = daily_count
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


async def make_hunter_runner(telegram_send_fn):
    """CommentHunter 1회 실행 래퍼 팩토리.

    Args:
        telegram_send_fn: async fn(text: str) -> Any
            텔레그램으로 리플 초안 카드 전송. 반환값 무시.

    Returns:
        run_hunter_fn — async () -> int (생성된 초안 수)
    """
    from app.services.growth.comment_hunter import CommentHunter, generate_reply_draft

    hunter = CommentHunter()

    async def _run() -> int:
        try:
            targets = await hunter.hunt(max_results=10)
            count = 0
            for target in targets:
                try:
                    target.reply_draft = await generate_reply_draft(target)
                    card_text = (
                        f"💬 리플 초안\n\n"
                        f"대상: @{target.author_username}\n"
                        f"원문: {target.text[:100]}...\n\n"
                        f"초안:\n{target.reply_draft}\n\n"
                        f"좋아요: {target.like_count} | "
                        f"유형: {target.suggested_reply_type}"
                    )
                    await telegram_send_fn(card_text)
                    count += 1
                except Exception as e:
                    logger.warning(
                        f"[Hunter] 리플 초안 생성 실패 (무시): {e}"
                    )
            return count
        except Exception as e:
            logger.warning(f"[Hunter] hunt 실패 (무시): {e}")
            return 0

    return _run
