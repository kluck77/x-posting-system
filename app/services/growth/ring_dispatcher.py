"""Ring Dispatcher — 텔레그램 승인 카드를 KST 최적 시각에 전송.

Ring A (한국 독자 메인):
  07:30 / 12:00 / 18:30 / 22:30 KST
  하루 최대 6개 (Ring A + C 합산)

Ring C (Breaking 즉시):
  priority=0 인 draft 는 링 무관 즉시 전송
  하루 최대 Breaking 4개 별도 카운트

운영 원칙:
  - X 자동 포스팅 없음. 텔레그램 승인 요청만.
  - 승인은 운영자 수동.
  - 슬롯이 비어있으면 큐에서 다음 draft 꺼내 카드 전송.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

# KST = UTC+9
KST = timezone(timedelta(hours=9))

# Ring A 슬롯 시각 (KST 시:분)
RING_A_SLOTS: list[tuple[int, int]] = [
    (7, 30),
    (12, 0),
    (18, 30),
    (22, 30),
]

DAILY_CAP_RING_A = 6      # Ring A + C 하루 합산 최대
DAILY_CAP_BREAKING = 4    # Ring C Breaking 하루 최대
POLL_INTERVAL_SEC = 60    # 1분마다 슬롯 체크


def _now_kst() -> datetime:
    return datetime.now(KST)


def _next_slot_seconds(slots: list[tuple[int, int]]) -> float:
    """다음 Ring A 슬롯까지 남은 초."""
    now = _now_kst()
    today_slots = [
        now.replace(hour=h, minute=m, second=0, microsecond=0)
        for h, m in slots
    ]
    future = [s for s in today_slots if s > now]
    if future:
        return (future[0] - now).total_seconds()
    # 오늘 슬롯 모두 지남 → 내일 첫 슬롯
    tomorrow_first = today_slots[0] + timedelta(days=1)
    return (tomorrow_first - now).total_seconds()


def _is_slot_time(slots: list[tuple[int, int]], tolerance_sec: int = 90) -> bool:
    """현재 시각이 Ring A 슬롯 ±tolerance_sec 이내인지."""
    now = _now_kst()
    for h, m in slots:
        slot = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if abs((now - slot).total_seconds()) <= tolerance_sec:
            return True
    return False


async def ring_a_loop(send_next_card_fn, get_pending_count_fn) -> None:
    """Ring A 루프 — 슬롯 시각마다 대기 중 카드 1개 전송 요청.

    Args:
        send_next_card_fn: async fn() -> bool
            큐에서 다음 draft 꺼내 텔레그램 승인 카드 전송.
            전송 성공 True, 큐 비어있으면 False.
        get_pending_count_fn: fn() -> int
            현재 대기 중 draft 수.
    """
    daily_count = 0
    last_reset_date = _now_kst().date()

    while True:
        try:
            # 날짜 바뀌면 카운트 리셋
            today = _now_kst().date()
            if today != last_reset_date:
                daily_count = 0
                last_reset_date = today

            if daily_count >= DAILY_CAP_RING_A:
                await asyncio.sleep(POLL_INTERVAL_SEC * 10)
                continue

            if _is_slot_time(RING_A_SLOTS):
                pending = get_pending_count_fn()
                if pending > 0:
                    sent = await send_next_card_fn()
                    if sent:
                        daily_count += 1
                        logger.info(
                            f"[Ring A] 카드 전송. 오늘 {daily_count}/{DAILY_CAP_RING_A}. "
                            f"KST {_now_kst().strftime('%H:%M')}"
                        )
                    await asyncio.sleep(POLL_INTERVAL_SEC * 5)
                    continue

            await asyncio.sleep(POLL_INTERVAL_SEC)

        except asyncio.CancelledError:
            logger.info("[Ring A] 루프 종료")
            break
        except Exception as e:
            logger.warning(f"[Ring A] 오류 (무시): {e}")
            await asyncio.sleep(POLL_INTERVAL_SEC)


async def ring_c_loop(send_breaking_card_fn, get_breaking_pending_fn) -> None:
    """Ring C 루프 — Breaking priority=0 draft 즉시 전송.

    Args:
        send_breaking_card_fn: async fn() -> bool
        get_breaking_pending_fn: fn() -> int
    """
    daily_breaking = 0
    last_reset_date = _now_kst().date()

    while True:
        try:
            today = _now_kst().date()
            if today != last_reset_date:
                daily_breaking = 0
                last_reset_date = today

            if daily_breaking >= DAILY_CAP_BREAKING:
                await asyncio.sleep(POLL_INTERVAL_SEC * 5)
                continue

            pending = get_breaking_pending_fn()
            if pending > 0:
                sent = await send_breaking_card_fn()
                if sent:
                    daily_breaking += 1
                    logger.info(
                        f"[Ring C] Breaking 카드 전송. "
                        f"오늘 {daily_breaking}/{DAILY_CAP_BREAKING}"
                    )
                    await asyncio.sleep(30)
                    continue

            await asyncio.sleep(POLL_INTERVAL_SEC // 2)

        except asyncio.CancelledError:
            logger.info("[Ring C] 루프 종료")
            break
        except Exception as e:
            logger.warning(f"[Ring C] 오류 (무시): {e}")
            await asyncio.sleep(POLL_INTERVAL_SEC)
