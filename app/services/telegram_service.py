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
from zoneinfo import ZoneInfo
from app.config import settings
from app.models.content import Draft, RiskLevel, ContentCategory

KST = ZoneInfo("Asia/Seoul")

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

    # topic tags (Layer 2, advisory)
    try:
        _tags = getattr(draft, "topic_tags", None)
        if _tags:
            _tag_list = json.loads(_tags)
            if _tag_list:
                tag_str = " ".join(f"#{t.lstrip('#')}" for t in _tag_list[:5])
                card += f"🏷 {tag_str}\n"
    except Exception:
        pass

    if getattr(draft, "community_warning", None):
        card += (
            f"\n{'─' * 30}\n"
            f"⚠️ <b>커뮤니티 입력 경고</b>\n"
            f"{draft.community_warning}\n"
        )

    if getattr(draft, "predicted_publish_at", None):
        kst_time = draft.predicted_publish_at.astimezone(KST)
        card += f"⏰ <b>예측 최적 게시 시간:</b> {kst_time.strftime('%m/%d(%a) %H:%M KST')}\n"
        if getattr(draft, "prediction_reasoning", None):
            card += f"   └ {draft.prediction_reasoning}\n"

    # 5-criteria 실시간 평가
    try:
        from app.services.quality_scorer import score_5criteria, format_5criteria_report
        criteria_result = score_5criteria(draft.hook, draft.body)
        if criteria_result["action"] != "pass" or criteria_result["flags"]:
            card += f"\n{'─' * 30}\n"
            card += f"🔬 <b>5-Criteria 품질 분석:</b> {criteria_result['total']}/100\n"
            for flag in criteria_result["flags"]:
                card += f"  {flag}\n"
    except Exception:
        pass

    # quality advisory — 초안 우선순위 레이블 (Layer 2, advisory only)
    try:
        from app.services.advisory import draft_advisory
        _adv = draft_advisory(draft.hook, draft.body, getattr(draft, "source_type", "news_link"))
        if _adv:
            card += (
                f"\n{'─' * 30}\n"
                f"📌 <b>초안 우선순위:</b> {_adv} (참고용)\n"
            )
    except Exception:
        pass

    # VoiceGuard — 단일 초안 AI 어투 감지 (Layer 2, advisory only)
    try:
        from app.services.voice_guard import check_voice
        _voice_warnings = check_voice(f"{draft.hook}\n{draft.body}")
        if _voice_warnings:
            card += f"\n{'─' * 30}\n"
            card += "🗣️ <b>Voice 경고</b> (참고용):\n"
            for _w in _voice_warnings[:3]:
                card += f"  {_w}\n"
    except Exception:
        pass

    # Phase 5: 비즈니스 분류 표시 (Layer 2, advisory only)
    try:
        _biz_tags_raw = getattr(draft, "business_tags", None)
        if _biz_tags_raw:
            _biz_tags = json.loads(_biz_tags_raw)
            if _biz_tags and _biz_tags != ["growth"]:
                _mon_score = getattr(draft, "monetization_score", None) or 0
                _cta = getattr(draft, "cta_type", None) or "—"
                _asset = getattr(draft, "asset_goal", None) or "—"
                card += f"\n{'─' * 30}\n"
                card += f"💼 <b>비즈니스:</b> {' '.join(_biz_tags)}\n"
                card += f"   💰 수익화: {_mon_score}/100 | 🎯 CTA: {_cta} | 📦 자산: {_asset}\n"
                if getattr(draft, "b2b_candidate", False):
                    _b2b_aud = getattr(draft, "b2b_target_audience", None) or "—"
                    _b2b_use = getattr(draft, "b2b_use_case", None) or "—"
                    card += f"   🏢 B2B: {_b2b_aud} / {_b2b_use}\n"
                if getattr(draft, "premium_reason", None):
                    card += f"   ⭐ 프리미엄: {draft.premium_reason[:100]}\n"
    except Exception:
        pass

    char_info = f"Characters: {draft.text_length}"
    if draft.text_length > 280:
        char_info += " ⚠️ X 한도 초과 — 편집 필요"

    card += (
        f"\n💡 <b>Recommendation:</b> {_recommended_action(draft)}\n"
        f"{'─' * 30}\n"
        f"Draft ID: {draft.id} | Version: {draft.version}\n"
        f"{char_info}"
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


def build_analysis_card(
    title: str,
    content_type: str,
    research_summary: str,
    factcheck_summary: str,
    char_count: int,
) -> str:
    """
    URL/사진 분석 결과 카드 텍스트를 생성합니다.
    이 카드 아래에 '게시글로 / 댓글로 / 취소' 버튼이 붙습니다.
    """
    card = (
        f"🔍 <b>분석 완료</b>\n"
        f"{'─' * 30}\n\n"
        f"📰 <b>제목/주제:</b>\n{title[:200]}\n\n"
        f"📋 <b>유형:</b> {content_type}\n\n"
    )
    if research_summary:
        card += f"🔬 <b>핵심 내용:</b>\n{research_summary[:400]}\n\n"
    if factcheck_summary:
        card += f"✅ <b>팩트체크:</b>\n{factcheck_summary[:300]}\n\n"
    card += (
        f"{'─' * 30}\n"
        f"📏 추출 텍스트: {char_count}자\n\n"
        f"<b>어떻게 사용할까요?</b>"
    )
    return card


def build_type_selection_keyboard(pending_id: str) -> dict:
    """
    '게시글로 / 댓글로 / 취소' 인라인 키보드.
    pending_id = 상태 저장 키 (보통 str(message_id))
    """
    return {
        "inline_keyboard": [
            [
                {"text": "📝 새 게시글", "callback_data": f"type_tweet:{pending_id}"},
                {"text": "💬 댓글로", "callback_data": f"type_reply:{pending_id}"},
            ],
            [
                {"text": "❌ 취소", "callback_data": f"type_cancel:{pending_id}"},
            ],
        ]
    }


async def send_analysis_card(
    title: str,
    content_type: str,
    research_summary: str,
    factcheck_summary: str,
    char_count: int,
    pending_id: str,
) -> int | None:
    """
    분석 카드를 텔레그램으로 전송합니다.
    Returns: 전송된 message_id, 실패 시 None
    """
    if not settings.has_telegram_config:
        logger.info("[MOCK 텔레그램] 분석 카드 전송 스킵")
        return None

    card_text = build_analysis_card(
        title, content_type, research_summary, factcheck_summary, char_count
    )
    keyboard = build_type_selection_keyboard(pending_id)

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
            logger.error(f"분석 카드 전송 오류: {result}")
            return None
    except httpx.HTTPError as e:
        logger.error(f"분석 카드 전송 실패: {e}")
        return None


def send_content_pack_messages(pack) -> list[dict]:
    """
    ContentPack을 텔레그램 전송용 메시지 목록으로 변환합니다.
    실제 전송은 telegram_bot.py의 update.message.reply_text()가 담당합니다.

    Returns:
        [{"text": str, "pack_index": int | None, "post_text": str | None}, ...]
        pack_index: None = 참조용(버튼 없음), 0-2 = 메인포스트, 10 = 짧은버전
    """
    messages: list[dict] = []

    # ── 1. 개요 카드 ──────────────────────────────────────────────────────────
    overview_lines = ["📦 <b>콘텐츠 팩 생성 완료</b>\n"]

    if pack.why_it_matters:
        overview_lines.append(f"🌏 <b>Why it matters</b>\n{pack.why_it_matters}\n")

    if pack.topic_tags:
        tags = " ".join(f"#{t}" for t in pack.topic_tags)
        overview_lines.append(f"🏷 {tags}\n")

    if pack.risk_flags:
        flags = "\n".join(f"  • {f}" for f in pack.risk_flags)
        overview_lines.append(f"⚠️ <b>Risk flags</b>\n{flags}\n")

    if pack.style_warnings:
        warns = "\n".join(f"  • {w}" for w in pack.style_warnings)
        overview_lines.append(f"🔄 <b>Style warnings</b>\n{warns}\n")

    overview_lines.append(
        f"<i>메인 {len(pack.main_posts)}개 · 짧은버전 1개 · 댓글초안 {len(pack.reply_drafts)}개"
        f" · 인용 {len(pack.quote_post_drafts)}개"
        + (" · 스레드 있음" if pack.thread_option else "")
        + "</i>"
    )

    messages.append({"text": "\n".join(overview_lines), "pack_index": None, "post_text": None})

    # ── 2. 메인 포스트 × 3 (승인 버튼 있음) ──────────────────────────────────
    for i, post in enumerate(pack.main_posts[:3]):
        label = ["A", "B", "C"][i]
        text = f"📝 <b>메인 포스트 {label}</b>\n\n<code>{post}</code>"
        messages.append({"text": text, "pack_index": i, "post_text": post})

    # ── 3. 짧은 버전 (승인 버튼 있음, pack_index=10) ─────────────────────────
    if pack.short_version:
        text = f"⚡ <b>짧은 버전</b>\n\n<code>{pack.short_version}</code>"
        messages.append({"text": text, "pack_index": 10, "post_text": pack.short_version})

    # ── 4. 댓글 초안 × 3 (복사 전용 — 버튼 없음) ────────────────────────────
    if pack.reply_drafts:
        reply_text = "💬 <b>댓글 초안</b> (복사해서 사용)\n\n"
        for j, r in enumerate(pack.reply_drafts[:3], 1):
            reply_text += f"{j}. <code>{r}</code>\n\n"
        messages.append({"text": reply_text.strip(), "pack_index": None, "post_text": None})

    # ── 5. 인용 포스트 × 2 (복사 전용) ──────────────────────────────────────
    if pack.quote_post_drafts:
        quote_text = "🔁 <b>인용 포스트</b> (복사해서 사용)\n\n"
        for j, q in enumerate(pack.quote_post_drafts[:2], 1):
            quote_text += f"{j}. <code>{q}</code>\n\n"
        messages.append({"text": quote_text.strip(), "pack_index": None, "post_text": None})

    # ── 6. 스레드 옵션 (복사 전용) ───────────────────────────────────────────
    if pack.thread_option:
        thread_text = (
            f"🧵 <b>스레드 시작</b> (복사해서 사용)\n\n"
            f"<code>{pack.thread_option}</code>"
        )
        messages.append({"text": thread_text, "pack_index": None, "post_text": None})

    return messages


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
