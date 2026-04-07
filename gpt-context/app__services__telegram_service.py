# app/services/telegram_service.py
# 승인 카드 텍스트 생성: build_approval_card() 함수 (61번 줄)
# predicted_publish_at 줄을 카드에 추가할 위치: card += ... 블록 내부

import json
import logging
import httpx
from app.config import settings
from app.models.content import Draft, RiskLevel, ContentCategory

logger = logging.getLogger(__name__)
TELEGRAM_API_BASE = "https://api.telegram.org/bot{token}"


def _get_api_url(method: str) -> str:
    return f"{TELEGRAM_API_BASE.format(token=settings.telegram_bot_token)}/{method}"


def _risk_emoji(risk: RiskLevel) -> str:
    return {"low": "\U0001f7e2", "medium": "\U0001f7e1", "high": "\U0001f534"}.get(risk.value, "\u26aa")


def _category_emoji(category: ContentCategory) -> str:
    return {
        "politics": "\U0001f3db\ufe0f",
        "policy": "\U0001f4cb",
        "economy": "\U0001f4c8",
        "society": "\U0001f3d8\ufe0f",
        "kpop_culture": "\U0001f3b5",
        "evergreen": "\U0001f33f",
    }.get(category.value, "\U0001f4dd")


def _recommended_action(draft: Draft) -> str:
    if draft.risk_level == RiskLevel.HIGH:
        return "\u26a0\ufe0f CAREFUL REVIEW recommended"
    elif draft.risk_level == RiskLevel.MEDIUM:
        return "\U0001f440 Review before approving"
    else:
        return "\u2705 Looks safe to approve"


def build_approval_card(draft: Draft, source_url: str | None = None) -> str:
    """
    텔레그램으로 보낼 승인 카드 텍스트를 생성합니다.
    [TODO] predicted_publish_at 필드를 여기에 추가해야 합니다.
    """
    risk_em = _risk_emoji(draft.risk_level)
    cat_em = _category_emoji(draft.category)

    card = (
        f"\U0001f4e8 <b>NEW DRAFT FOR REVIEW</b>\n"
        f"{'\u2500' * 30}\n\n"
        f"\U0001f3af <b>Hook:</b>\n{draft.hook}\n\n"
        f"\U0001f4dd <b>Post Text:</b>\n{draft.body}\n\n"
    )

    if draft.thread_continuation:
        card += f"\U0001f9f5 <b>Thread:</b>\n{draft.thread_continuation}\n\n"

    card += (
        f"{cat_em} <b>Category:</b> {draft.category.value}\n"
        f"{risk_em} <b>Risk:</b> {draft.risk_level.value.upper()}\n"
    )

    if source_url:
        card += f"\U0001f517 <b>Source:</b> {source_url}\n"

    if draft.risk_reasoning:
        card += f"\U0001f4ca <b>Risk Reasoning:</b> {draft.risk_reasoning}\n"

    if draft.ai_rationale:
        card += f"\U0001f916 <b>AI Rationale:</b> {draft.ai_rationale}\n"

    # [TODO] predicted_publish_at 표시 추가 위치:
    # if hasattr(draft, 'predicted_publish_at') and draft.predicted_publish_at:
    #     from zoneinfo import ZoneInfo
    #     KST = ZoneInfo("Asia/Seoul")
    #     kst_time = draft.predicted_publish_at.astimezone(KST)
    #     card += f"\u23f0 <b>예측 최적 게시 시간:</b> {kst_time.strftime('%Y-%m-%d %H:%M KST')}\n"
    #     if draft.prediction_reasoning:
    #         card += f"   ({draft.prediction_reasoning})\n"

    card += (
        f"\n\U0001f4a1 <b>Recommendation:</b> {_recommended_action(draft)}\n"
        f"{'\u2500' * 30}\n"
        f"Draft ID: {draft.id} | Version: {draft.version}\n"
        f"Characters: {draft.text_length}"
    )

    return card


def build_inline_keyboard(draft_id: int) -> dict:
    return {
        "inline_keyboard": [
            [
                {"text": "\u2705 Approve", "callback_data": f"approve:{draft_id}"},
                {"text": "\u274c Reject", "callback_data": f"reject:{draft_id}"},
            ],
            [
                {"text": "\u23f8\ufe0f Defer", "callback_data": f"defer:{draft_id}"},
                {"text": "\U0001f504 Regenerate", "callback_data": f"regenerate:{draft_id}"},
            ],
        ]
    }


async def send_approval_card(draft: Draft, source_url: str | None = None) -> int | None:
    if not settings.has_telegram_config:
        logger.info(f"[MOCK] {build_approval_card(draft, source_url)}")
        return None
    card_text = build_approval_card(draft, source_url)
    keyboard = build_inline_keyboard(draft.id)
    payload = {
        "chat_id": settings.telegram_chat_id,
        "text": card_text,
        "parse_mode": "HTML",
        "reply_markup": json.dumps(keyboard),
    }
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(_get_api_url("sendMessage"), data=payload)
            response.raise_for_status()
            result = response.json()
            if result.get("ok"):
                return result["result"]["message_id"]
            return None
    except httpx.HTTPError as e:
        logger.error(f"텔레그램 전송 실패: {e}")
        return None
