"""
파이프라인 활동 추적기.
/draft, /queue add 등 실질적 작업 발생 시 타임스탬프를 기록.
48시간 이상 활동이 없으면 Telegram 유휴 알림을 발송한다 (하루 1회 제한).

data/activity.json에 저장.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

_STATE_FILE = Path("data/activity.json")
IDLE_HOURS = 48
REMINDER_COOLDOWN_HOURS = 24
KST = ZoneInfo("Asia/Seoul")


def _load() -> dict:
    try:
        return json.loads(_STATE_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except Exception as e:
        logger.warning(f"activity_tracker 로드 실패: {e}")
        return {}


def _save(state: dict) -> None:
    try:
        _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _STATE_FILE.write_text(
            json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception as e:
        logger.error(f"activity_tracker 저장 실패: {e}")


def record_activity() -> None:
    """파이프라인 활동 기록 (초안 생성, 큐 추가 등)."""
    state = _load()
    state["last_activity_at"] = datetime.now(timezone.utc).isoformat()
    _save(state)


def get_last_activity() -> datetime | None:
    """마지막 활동 시각 반환. 없으면 None."""
    raw = _load().get("last_activity_at")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except Exception:
        return None


def should_send_idle_reminder() -> bool:
    """
    유휴 알림을 보내야 하면 True.
    조건:
      - 마지막 활동이 IDLE_HOURS(48h) 이상 경과
      - 마지막 알림으로부터 REMINDER_COOLDOWN_HOURS(24h) 이상 경과
      - 활동 기록 자체가 없으면 False (시스템 최초 실행 과잉 알림 방지)
    """
    state = _load()
    now = datetime.now(timezone.utc)

    last_activity_raw = state.get("last_activity_at")
    if not last_activity_raw:
        # 한 번도 활동 기록이 없으면 알림 불필요
        return False

    try:
        last_activity = datetime.fromisoformat(last_activity_raw)
    except Exception:
        return False

    if (now - last_activity).total_seconds() < IDLE_HOURS * 3600:
        return False

    last_reminder_raw = state.get("last_reminder_at")
    if last_reminder_raw:
        try:
            last_reminder = datetime.fromisoformat(last_reminder_raw)
            if (now - last_reminder).total_seconds() < REMINDER_COOLDOWN_HOURS * 3600:
                return False
        except Exception:
            pass

    return True


def record_reminder_sent() -> None:
    """유휴 알림 발송 후 타임스탬프 기록."""
    state = _load()
    state["last_reminder_at"] = datetime.now(timezone.utc).isoformat()
    _save(state)


async def check_and_send_idle_reminder() -> None:
    """
    스케줄러가 매 60분 호출.
    유휴 조건 충족 시 Telegram 유휴 알림 발송.
    Layer 2 — 실패해도 시스템에 영향 없음.
    """
    try:
        if not should_send_idle_reminder():
            return

        last = get_last_activity()
        if last:
            elapsed_h = int((datetime.now(timezone.utc) - last).total_seconds() // 3600)
            last_kst = last.astimezone(KST)
            time_str = f"{last_kst.strftime('%m/%d %H:%M KST')} ({elapsed_h}시간 전)"
        else:
            time_str = "기록 없음"

        from app.services.growth._tg_helper import tg_send
        msg = (
            "⏰ <b>파이프라인 유휴 알림</b>\n\n"
            f"마지막 활동: {time_str}\n\n"
            "콘텐츠 작업이 48시간 이상 없었어요.\n"
            "시작하려면:\n"
            "<code>/draft https://뉴스URL</code>\n"
            "또는 URL을 바로 전송해주세요."
        )
        await tg_send(msg)
        record_reminder_sent()
        logger.info("유휴 파이프라인 알림 발송 완료")
    except Exception as e:
        logger.error(f"유휴 알림 처리 실패: {e}")
