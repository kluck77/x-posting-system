"""
텔레그램 승인 서비스
====================
텔레그램으로 승인 카드를 보내고, 사용자의 버튼 응답을 처리합니다.

승인 카드에는 다음이 포함됩니다:
- 훅/제목
- 포스트 전문
- 카테고리
- 위험 수준
- 소스 링크
- AI 판단 근거
- 추천 액션
- 버튼: Approve / Reject / Defer / Regenerate
"""

import json
import logging
import httpx
from app.config import settings
from app.models.content import Draft, RiskLevel, ContentCategory, SourceItem

logger = logging.getLogger(__name__)

# 텔레그램 Bot API 기본 URL
TELEGRAM_API_BASE = "https://api.telegram.org/bot{token}"


def _get_api_url(method: str) -> str:
    """텔레그램 API URL을 생성합니다."""
    return f"{TELEGRAM_API_BASE.format(token=settings.telegram_bot_token)}/{method}"


def _risk_emoji(risk: RiskLevel) -> str:
    """위험 수준에 맞는 이모지를 반환합니다."""
    return {"low": "🟢", "medium": "🟡", "high": "🔴"}.get(risk.value, "⚪")


def _category_emoji(category: ContentCategory) -> str:
    """카테고리에 맞는 이모지를 반환합니다."""
    return {
        "politics": "🏛️",
        "policy": "📋",
        "economy": "📈",
        "society": "🏘️",
        "kpop_culture": "🎵",
        "evergreen": "🌿",
    }.get(category.value, "📝")


def _recommended_action(draft: Draft) -> str:
    """위험 수준에 따른 추천 액션을 반환합니다."""
    if draft.risk_level == RiskLevel.HIGH:
        return "⚠️ CAREFUL REVIEW recommended"
    elif draft.risk_level == RiskLevel.MEDIUM:
        return "👀 Review before approving"
    else:
        return "✅ Looks safe to approve"


def build_approval_card(draft: Draft, source_url: str | None = None) -> str:
    """
    텔레그램으로 보낼 승인 카드 텍스트를 생성합니다.

    Args:
        draft: 검토할 초안
        source_url: 원본 소스 URL

    Returns:
        마크다운 포맷의 카드 텍스트
    """
    risk_em = _risk_emoji(draft.risk_level)
    cat_em = _category_emoji(draft.category)

    # 텔레그램 MarkdownV2에서 특수문자 이스케이프
    # 간단하게 HTML 모드를 사용합니다
    card = (
        f"📨 <b>NEW DRAFT FOR REVIEW</b>\n"
        f"{'─' * 30}\n\n"
        f"🎯 <b>Hook:</b>\n{draft.hook}\n\n"
        f"📝 <b>Post Text:</b>\n{draft.body}\n\n"
    )

    if draft.thread_continuation:
        card += f"🧵 <b>Thread:</b>\n{draft.thread_continuation}\n\n"

    card += (
        f"{cat_em} <b>Category:</b> {draft.category.value}\n"
        f"{risk_em} <b>Risk:</b> {draft.risk_level.value.upper()}\n"
    )

    if source_url:
        card += f"🔗 <b>Source:</b> {source_url}\n"

    if draft.risk_reasoning:
        card += f"📊 <b>Risk Reasoning:</b> {draft.risk_reasoning}\n"

    if draft.ai_rationale:
        card += f"🤖 <b>AI Rationale:</b> {draft.ai_rationale}\n"

    card += (
        f"\n💡 <b>Recommendation:</b> {_recommended_action(draft)}\n"
        f"{'─' * 30}\n"
        f"Draft ID: {draft.id} | Version: {draft.version}\n"
        f"Characters: {draft.text_length}"
    )

    return card


def build_inline_keyboard(draft_id: int) -> dict:
    """
    승인/거절 버튼이 포함된 인라인 키보드를 생성합니다.

    callback_data 형식: "action:draft_id"
    예: "approve:42", "reject:42"
    """
    keyboard = {
        "inline_keyboard": [
            [
                {"text": "✅ Approve", "callback_data": f"approve:{draft_id}"},
                {"text": "❌ Reject", "callback_data": f"reject:{draft_id}"},
            ],
            [
                {"text": "⏸️ Defer", "callback_data": f"defer:{draft_id}"},
                {"text": "🔄 Regenerate", "callback_data": f"regenerate:{draft_id}"},
            ],
        ]
    }
    return keyboard


async def send_approval_card(draft: Draft, source_url: str | None = None) -> int | None:
    """
    텔레그램으로 승인 카드를 전송합니다.

    Args:
        draft: 검토할 초안
        source_url: 원본 소스 URL

    Returns:
        전송된 메시지의 message_id, 실패 시 None
    """
    if not settings.has_telegram_config:
        logger.warning("텔레그램 설정이 없습니다. 카드 전송을 건너뜁니다.")
        logger.info(f"[MOCK 텔레그램] 승인 카드:\n{build_approval_card(draft, source_url)}")
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
            response = await client.post(
                _get_api_url("sendMessage"),
                data=payload,
            )
            response.raise_for_status()
            result = response.json()

            if result.get("ok"):
                message_id = result["result"]["message_id"]
                logger.info(f"텔레그램 카드 전송 성공: message_id={message_id}, draft_id={draft.id}")
                return message_id
            else:
                logger.error(f"텔레그램 API 오류: {result}")
                return None

    except httpx.HTTPError as e:
        logger.error(f"텔레그램 전송 실패: {e}")
        return None


async def send_publish_confirmation(draft: Draft) -> None:
    """
    X에 게시 완료 후 텔레그램으로 확인 메시지를 보냅니다.
    """
    if not settings.has_telegram_config:
        logger.info(f"[MOCK 텔레그램] 게시 확인: draft_id={draft.id}, x_post_id={draft.x_post_id}")
        return

    text = (
        f"✅ <b>POSTED TO X</b>\n\n"
        f"📝 {draft.hook}\n\n"
        f"🆔 Post ID: {draft.x_post_id}\n"
        f"🔗 {draft.x_post_url or 'URL not available'}\n"
        f"📊 Category: {draft.category.value} | Risk: {draft.risk_level.value}"
    )

    payload = {
        "chat_id": settings.telegram_chat_id,
        "text": text,
        "parse_mode": "HTML",
    }

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                _get_api_url("sendMessage"),
                data=payload,
            )
            if response.status_code == 200:
                logger.info(f"게시 확인 메시지 전송 완료: draft_id={draft.id}")
            else:
                logger.warning(f"게시 확인 메시지 전송 실패: {response.text}")
    except httpx.HTTPError as e:
        logger.error(f"게시 확인 메시지 전송 오류: {e}")


def parse_callback_data(callback_data: str) -> tuple[str, int] | None:
    """
    텔레그램 인라인 버튼의 callback_data를 파싱합니다.

    Args:
        callback_data: "action:draft_id" 형식의 문자열

    Returns:
        (action, draft_id) 튜플, 파싱 실패 시 None
    """
    try:
        parts = callback_data.split(":")
        if len(parts) != 2:
            return None
        action = parts[0]
        draft_id = int(parts[1])
        if action not in ("approve", "reject", "defer", "regenerate"):
            return None
        return (action, draft_id)
    except (ValueError, IndexError):
        logger.warning(f"잘못된 callback_data: {callback_data}")
        return None


# =============================================================================
# Phase A — Hold Queue 카드 (heuristic 45~59 구간 source_item 알림용)
# =============================================================================
#
# 승인 flow(approve/reject/defer/regenerate)는 전혀 건드리지 않는다.
# Hold 카드는 완전히 별도 메시지이며, callback_data 도 네임스페이스가 다르다:
#   "hold_promote:<source_id>"
#   "hold_discard:<source_id>"
#   "hold_mark24:<source_id>"
#
# 24h 자동 폐기 스케줄러는 Phase A 범위 밖이다.
# "24h표시" 버튼은 "표시만" 하는 용도이며 실제 자동 처리는 하지 않는다.


def build_hold_card(source_item: SourceItem) -> str:
    """
    Hold 상태 source_item 에 대한 텔레그램 카드 텍스트.
    """
    score = source_item.candidate_score
    score_text = str(score) if score is not None else "?"

    title = source_item.title or ""
    if len(title) > 140:
        title = title[:140] + "..."

    preview = (source_item.source_text or "")[:240]
    if len(source_item.source_text or "") > 240:
        preview += "..."

    card = (
        f"🟡 <b>HOLD QUEUE (Phase A)</b>\n"
        f"{'─' * 30}\n\n"
        f"📰 <b>Title:</b>\n{title}\n\n"
        f"📝 <b>Preview:</b>\n{preview}\n\n"
        f"📊 <b>Heuristic Score:</b> {score_text} / 85\n"
    )

    if source_item.url:
        card += f"🔗 <b>Source:</b> {source_item.url}\n"

    card += (
        f"{'─' * 30}\n"
        f"Source ID: {source_item.id}\n"
        f"Status: hold (컷라인 45~59)\n"
    )
    return card


def build_hold_inline_keyboard(source_id: int) -> dict:
    """
    Hold 카드 버튼 3개.
    - 승격:    이 source 를 passed 로 승격하여 초안 생성 파이프라인에 태움
    - 폐기:    rejected_manual 로 내림
    - 24h표시: "운영자가 지금 봤음" 이라는 표시만 남김 (자동 폐기 없음)
    """
    return {
        "inline_keyboard": [
            [
                {"text": "⬆️ 승격",   "callback_data": f"hold_promote:{source_id}"},
                {"text": "🗑️ 폐기",   "callback_data": f"hold_discard:{source_id}"},
            ],
            [
                {"text": "⏱️ 24h표시", "callback_data": f"hold_mark24:{source_id}"},
            ],
        ]
    }


async def send_hold_card(source_item: SourceItem) -> int | None:
    """
    Hold queue 카드를 텔레그램으로 전송한다.
    텔레그램 미설정이면 로그 출력만 하고 None 반환.
    """
    if not settings.has_telegram_config:
        logger.warning("텔레그램 설정이 없습니다. Hold 카드 전송을 건너뜁니다.")
        logger.info(f"[MOCK 텔레그램] Hold 카드:\n{build_hold_card(source_item)}")
        return None

    card_text = build_hold_card(source_item)
    keyboard = build_hold_inline_keyboard(source_item.id)

    payload = {
        "chat_id": settings.telegram_chat_id,
        "text": card_text,
        "parse_mode": "HTML",
        "reply_markup": json.dumps(keyboard),
    }

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                _get_api_url("sendMessage"),
                data=payload,
            )
            response.raise_for_status()
            result = response.json()

            if result.get("ok"):
                message_id = result["result"]["message_id"]
                logger.info(
                    f"Hold 카드 전송 성공: message_id={message_id}, "
                    f"source_id={source_item.id}"
                )
                return message_id
            else:
                logger.error(f"텔레그램 API 오류 (hold): {result}")
                return None

    except httpx.HTTPError as e:
        logger.error(f"Hold 카드 전송 실패: {e}")
        return None


def parse_hold_callback_data(callback_data: str) -> tuple[str, int] | None:
    """
    Hold 카드 버튼의 callback_data 파싱.
    포맷: "hold_<action>:<source_id>"

    허용 action: hold_promote / hold_discard / hold_mark24

    Returns:
        (action, source_id) 튜플, 실패 시 None
    """
    try:
        parts = callback_data.split(":")
        if len(parts) != 2:
            return None
        action = parts[0]
        source_id = int(parts[1])
        if action not in ("hold_promote", "hold_discard", "hold_mark24"):
            return None
        return (action, source_id)
    except (ValueError, IndexError):
        logger.warning(f"잘못된 hold callback_data: {callback_data}")
        return None
