"""Growth 모듈 공용 Telegram 전송 헬퍼."""
import logging
import httpx
from app.config import settings

logger = logging.getLogger(__name__)


def _tg_url(method: str) -> str:
    return f"https://api.telegram.org/bot{settings.telegram_bot_token}/{method}"


async def tg_send(text: str, parse_mode: str = "HTML", disable_preview: bool = True) -> bool:
    """Telegram 메시지 전송. 4096자 초과 시 잘림."""
    if not settings.has_telegram_config:
        logger.info(f"[Mock TG] {text[:80]}")
        return True
    payload = {
        "chat_id": settings.telegram_chat_id,
        "text": text[:4000],
        "parse_mode": parse_mode,
        "disable_web_page_preview": disable_preview,
    }
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.post(_tg_url("sendMessage"), data=payload)
            return r.status_code == 200
    except Exception as e:
        logger.error(f"Telegram 전송 실패: {e}")
        return False
