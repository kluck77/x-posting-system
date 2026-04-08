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
from app.models.content import Draft, RiskLevel, ContentCategory

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


# 운영자 한국어 요약 블록용 라벨 맵 (render-time only, 스키마/프롬프트 무변경)
_CATEGORY_KR = {
    "politics": "정치",
    "policy": "정책",
    "economy": "경제",
    "society": "사회",
    "kpop_culture": "K-POP/문화",
    "evergreen": "에버그린",
}
_RISK_KR = {"low": "낮음", "medium": "중간", "high": "높음"}
_RECOMMEND_KR = {
    "low": "✅ 승인 안전",
    "medium": "👀 검토 후 승인",
    "high": "⚠️ 신중 검토 권장",
}


def _korean_summary_block(draft: Draft) -> str:
    """
    승인 카드용 한국어 요약 블록 (render-time only).

    기존 영어 섹션을 건드리지 않고, 카테고리/위험도/추천의 한국어 라벨을
    1줄로 표시한다. risk_reasoning / ai_rationale 이 있으면 있는 그대로
    pass-through 2차 라인에 덧붙인다 (영어이면 영어 그대로 노출).

    저장/스키마/프롬프트 변경 없음. Draft 의 기존 컬럼만 사용.
    """
    cat_ko = _CATEGORY_KR.get(draft.category.value, draft.category.value)
    risk_ko = _RISK_KR.get(draft.risk_level.value, draft.risk_level.value.upper())
    rec_ko = _RECOMMEND_KR.get(draft.risk_level.value, "검토")
    lines = [
        "🇰🇷 <b>운영자 요약 (한국어)</b>",
        f"카테고리: {cat_ko} · 위험도: {risk_ko} · 추천: {rec_ko}",
    ]
    if getattr(draft, "risk_reasoning", None):
        lines.append(f"사유: {draft.risk_reasoning}")
    if getattr(draft, "ai_rationale", None):
        lines.append(f"판단: {draft.ai_rationale}")
    return "\n".join(lines)


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

    # 운영자 한국어 요약 블록 (render-time, 스키마/프롬프트 무변경)
    card += f"\n{_korean_summary_block(draft)}\n"

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


_APPROVAL_ACTIONS = ("approve", "reject", "defer", "regenerate")
_HOLD_ACTIONS = ("hold_promote", "hold_discard", "hold_mark24")


def parse_callback_data(callback_data: str) -> tuple[str, int] | None:
    """
    텔레그램 인라인 버튼의 callback_data를 파싱합니다.

    지원 형식: "action:item_id"
      - 승인 카드:  approve / reject / defer / regenerate
      - Hold 카드:  hold_promote / hold_discard / hold_mark24

    item_id는 카드 종류에 따라 draft_id 또는 candidate_id를 의미할 수 있으며,
    본 함수는 정수 파싱까지만 담당합니다 (호출부가 해석).

    Returns:
        (action, item_id) 튜플, 파싱 실패 시 None
    """
    try:
        parts = callback_data.split(":")
        if len(parts) != 2:
            return None
        action = parts[0]
        item_id = int(parts[1])
        if action not in _APPROVAL_ACTIONS and action not in _HOLD_ACTIONS:
            return None
        return (action, item_id)
    except (ValueError, IndexError):
        logger.warning(f"잘못된 callback_data: {callback_data}")
        return None
