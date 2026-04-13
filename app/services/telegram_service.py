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
import html as html_mod
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


_CATEGORY_KO = {
    "politics": "정치", "policy": "정책", "economy": "경제",
    "society": "사회", "kpop_culture": "K-POP/문화", "evergreen": "에버그린",
}

_RISK_KO = {"low": "낮음", "medium": "보통", "high": "높음"}

_CTA_KO = {
    "newsletter_signup": "뉴스레터 구독", "premium_waitlist": "프리미엄 대기",
    "thread_follow": "스레드 팔로우", "poll_engage": "투표 참여",
}

_ASSET_KO = {
    "newsletter_push": "뉴스레터", "premium_teaser": "프리미엄 티저",
    "thread_series": "스레드 시리즈", "community_post": "커뮤니티 포스트",
}

_BIZ_TAG_KO = {
    "growth": "성장", "newsletter": "뉴스레터", "premium_candidate": "프리미엄 후보",
    "data_story": "데이터 스토리", "sponsor_candidate": "스폰서 후보",
}


def _recommended_action(
    draft: Draft,
    quality_action: str | None = None,
) -> str:
    """
    최종 추천 산정 — 품질 게이트 × 위험 게이트.

    이 함수는 승인 카드의 '추천' 라인을 만든다. 카드에 동시에 노출되는
    '5대 기준 품질 분석' (score_5criteria) 과 반드시 일관되어야 한다.

    품질 우선 원칙:
      - quality_action == "reject" (5-criteria total < 50)
        → 위험과 무관하게 ❌ 거절 권장
      - quality_action == "warn"   (50 ≤ total < 70)
        + 위험 HIGH  → ❌ 거절 권장 (품질 경고 + 고위험)
        + 위험 MED/LOW → ⚠️ 검토 필요 (품질 경고)
      - quality_action == "pass"   (total ≥ 70)
        + 위험 HIGH  → ⚠️ 신중한 검토 필요
        + 위험 MED   → 👀 승인 전 검토 권장
        + 위험 LOW   → ✅ 승인 가능
      - quality_action is None (scorer 실패/미호출)
        → 구식 위험-only 경로로 폴백 (기존 동작 보존)

    '초안 우선순위' 는 여기 반영하지 않는다 — 그건 '시의성' 축이고
    최종 추천은 품질+위험 축이다. 우선순위가 🔴 라도 품질이 낮으면
    절대 '승인 가능' 이 뜨지 않는다.
    """
    # 품질 게이트 — 최우선
    if quality_action == "reject":
        return "❌ 거절 권장 (품질 미달)"

    # 고위험 경로 — 품질 warn 과 결합되면 거절, 아니면 신중 검토
    if draft.risk_level == RiskLevel.HIGH:
        if quality_action == "warn":
            return "❌ 거절 권장 (품질 경고 + 고위험)"
        return "⚠️ 신중한 검토 필요"

    # 품질 경고는 위험 무관 검토 필요
    if quality_action == "warn":
        return "⚠️ 검토 필요 (품질 경고)"

    # 품질 OK 경로 — 위험별
    if draft.risk_level == RiskLevel.MEDIUM:
        return "👀 승인 전 검토 권장"
    return "✅ 승인 가능"


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

    # ── 5-criteria 품질 평가: 한 번 계산해서 카드 표시 + 추천 게이트에 공유.
    # 이전에는 표시/추천이 서로 다른 신호로 계산돼 '품질 20 + 추천 승인 가능' 모순이
    # 났다. 이 결과는 아래 5대 기준 표시 블록과 마지막 _recommended_action 호출이
    # 동시에 소비한다.
    quality_action: str | None = None
    criteria_result: dict | None = None
    try:
        from app.services.quality_scorer import score_5criteria
        criteria_result = score_5criteria(draft.hook, draft.body)
        quality_action = criteria_result.get("action")
    except Exception:
        logger.debug("[Card] 5-criteria 평가 실패", exc_info=True)

    # 내부 라우팅 문구 새니타이즈 (DB 기존 레코드 방어, fail-safe)
    try:
        from app.services.text_cleaner import sanitize_internal_tags, sanitize_reasoning
        _hook, _body = sanitize_internal_tags(draft.hook or "", draft.body or "")
    except Exception:
        _hook, _body = draft.hook or "", draft.body or ""

    # HTML 특수문자 이스케이프 (< > & 등이 있으면 Telegram 400 에러)
    _hook = html_mod.escape(_hook)
    _body = html_mod.escape(_body)

    card = (
        f"📨 <b>새 초안 검토 요청</b>\n"
        f"{'─' * 30}\n\n"
        f"🎯 <b>훅:</b>\n{_hook}\n\n"
    )
    if _body:
        # 본문이 너무 길면 4096자 제한 초과 → 잘라내기
        _body_display = _body[:2000] + "…" if len(_body) > 2000 else _body
        card += f"📝 <b>본문:</b>\n{_body_display}\n\n"
    else:
        card += "📝 <b>본문:</b>\n⚠️ 본문 없음 — 재생성 필요\n\n"

    if draft.thread_continuation:
        card += f"🧵 <b>스레드:</b>\n{draft.thread_continuation}\n\n"

    card += (
        f"{cat_em} <b>카테고리:</b> {_CATEGORY_KO.get(draft.category.value, draft.category.value)}\n"
        f"{risk_em} <b>위험도:</b> {_RISK_KO.get(draft.risk_level.value, draft.risk_level.value)}\n"
    )

    if source_url:
        card += f"🔗 <b>출처:</b> {source_url}\n"

    try:
        _risk_reason = sanitize_reasoning(draft.risk_reasoning or "")
    except Exception:
        _risk_reason = draft.risk_reasoning or ""
    if _risk_reason:
        card += f"📊 <b>위험 판단 근거:</b> {html_mod.escape(_risk_reason)}\n"

    try:
        _ai_rationale = sanitize_reasoning(draft.ai_rationale or "")
    except Exception:
        _ai_rationale = draft.ai_rationale or ""
    if _ai_rationale:
        card += f"🤖 <b>AI 판단 근거:</b> {html_mod.escape(_ai_rationale)}\n"

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

    # 5대 기준 품질 분석 — 위에서 계산한 criteria_result 를 재사용
    if criteria_result is not None and (
        criteria_result.get("action") != "pass" or criteria_result.get("flags")
    ):
        card += f"\n{'─' * 30}\n"
        card += f"🔬 <b>5대 기준 품질 분석:</b> {criteria_result['total']}/100\n"
        for flag in criteria_result.get("flags", []):
            card += f"  {flag}\n"

    # 초안 우선순위 레이블 — '시의성/운영 중요도' 기준 (품질과 독립)
    # source_type 은 Draft 에 직접 없다. SourceItem.source_type 에 있으므로
    # draft.source_item.source_type 으로 조회. 관계가 없거나 로드 실패해도
    # getattr fallback 으로 "news_link" 사용.
    try:
        from app.services.advisory import draft_advisory
        _src_type = "news_link"
        _si = getattr(draft, "source_item", None)
        if _si is not None:
            _src_type = getattr(_si, "source_type", None) or "news_link"
        _adv = draft_advisory(draft.hook, draft.body, _src_type)
        if _adv:
            card += (
                f"\n{'─' * 30}\n"
                f"📌 <b>초안 우선순위:</b> {_adv} "
                f"(시의성 기준, 품질과 독립)\n"
            )
    except Exception:
        logger.debug("[Card] 우선순위 라벨 계산 실패", exc_info=True)

    # VoiceGuard — 단일 초안 AI 어투 감지 (Layer 2, advisory only)
    try:
        from app.services.voice_guard import check_voice
        _voice_warnings = check_voice(f"{draft.hook}\n{draft.body}")
        if _voice_warnings:
            card += f"\n{'─' * 30}\n"
            card += "🗣️ <b>어투 경고</b> (참고용):\n"
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
                _biz_ko = [_BIZ_TAG_KO.get(t, t) for t in _biz_tags]
                card += f"💼 <b>비즈니스:</b> {' '.join(_biz_ko)}\n"
                _cta_ko = _CTA_KO.get(_cta, _cta)
                _asset_ko = _ASSET_KO.get(_asset, _asset)
                card += f"   💰 수익화: {_mon_score}/100 | 🎯 CTA: {_cta_ko} | 📦 자산: {_asset_ko}\n"
                if getattr(draft, "b2b_candidate", False):
                    _b2b_aud = getattr(draft, "b2b_target_audience", None) or "—"
                    _b2b_use = getattr(draft, "b2b_use_case", None) or "—"
                    card += f"   🏢 B2B: {_b2b_aud} / {_b2b_use}\n"
                if getattr(draft, "premium_reason", None):
                    card += f"   ⭐ 프리미엄: {draft.premium_reason[:100]}\n"
    except Exception:
        pass

    char_info = f"글자 수: {draft.text_length}"
    if draft.text_length > 280:
        char_info += " ⚠️ X 한도 초과 — 편집 필요"

    card += (
        f"\n💡 <b>추천:</b> "
        f"{_recommended_action(draft, quality_action=quality_action)}\n"
        f"{'─' * 30}\n"
        f"초안 ID: {draft.id} | 버전: {draft.version}\n"
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
                {"text": "✅ 승인", "callback_data": f"approve:{draft_id}"},
                {"text": "❌ 거절", "callback_data": f"reject:{draft_id}"},
            ],
            [
                {"text": "⏸️ 보류", "callback_data": f"defer:{draft_id}"},
                {"text": "🔄 재생성", "callback_data": f"regenerate:{draft_id}"},
            ],
        ]
    }
    return keyboard


async def send_approval_card(
    draft: Draft,
    source_url: str | None = None,
    chat_id: int | str | None = None,
) -> int | None:
    """
    텔레그램으로 승인 카드를 전송합니다.

    Args:
        draft: 검토할 초안
        source_url: 원본 소스 URL
        chat_id: 전송 대상 chat_id (None이면 settings.telegram_chat_id 사용)

    Returns:
        전송된 메시지의 message_id, 실패 시 None
    """
    if not settings.has_telegram_config:
        logger.warning("텔레그램 설정이 없습니다. 카드 전송을 건너뜁니다.")
        logger.info(f"[MOCK 텔레그램] 승인 카드:\n{build_approval_card(draft, source_url)}")
        return None

    target_chat = chat_id or settings.telegram_chat_id
    card_text = build_approval_card(draft, source_url)
    keyboard = build_inline_keyboard(draft.id)

    payload = {
        "chat_id": target_chat,
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


async def _translate_to_korean(text: str) -> str | None:
    """
    Gemini Flash로 영문 텍스트를 한국어로 번역합니다. (Layer 2 — 실패 시 None)
    """
    if not settings.has_gemini or not text:
        return None
    try:
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"gemini-2.5-flash:generateContent?key={settings.gemini_api_key}"
        )
        prompt = (
            "Translate the following English X/Twitter post into natural, concise Korean. "
            "Output ONLY the Korean translation — no quotes, no explanation.\n\n"
            f"{text}"
        )
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(
                url,
                json={"contents": [{"parts": [{"text": prompt}]}]},
            )
            r.raise_for_status()
            data = r.json()
            return data["candidates"][0]["content"]["parts"][0]["text"].strip()
    except Exception as e:
        safe_msg = str(e)
        if settings.gemini_api_key:
            safe_msg = safe_msg.replace(settings.gemini_api_key, "***")
        logger.warning(f"[Translate] 한국어 번역 실패: {safe_msg}")
        return None


async def send_publish_confirmation(draft: Draft) -> None:
    """
    X에 게시 완료 후 텔레그램으로 확인 메시지를 보냅니다.
    """
    if not settings.has_telegram_config:
        logger.info(f"[MOCK 텔레그램] 게시 확인: draft_id={draft.id}, x_post_id={draft.x_post_id}")
        return

    # 본문(hook + body)을 한국어로 번역 (Layer 2, 실패해도 진행)
    original_text = f"{draft.hook}\n\n{draft.body}"
    ko_translation = await _translate_to_korean(original_text)

    text = (
        f"✅ <b>X 게시 완료</b>\n\n"
        f"📝 <b>원문:</b>\n{draft.hook}\n\n{draft.body}\n\n"
    )
    if ko_translation:
        text += f"🇰🇷 <b>한국어:</b>\n{ko_translation}\n\n"
    text += (
        f"🆔 게시 ID: {draft.x_post_id}\n"
        f"🔗 {draft.x_post_url or 'URL 없음'}\n"
        f"📊 카테고리: {draft.category.value} | 위험도: {draft.risk_level.value}"
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
        overview_lines.append(f"🌏 <b>왜 중요한가</b>\n{pack.why_it_matters}\n")

    if pack.topic_tags:
        tags = " ".join(f"#{t}" for t in pack.topic_tags)
        overview_lines.append(f"🏷 {tags}\n")

    if pack.risk_flags:
        flags = "\n".join(f"  • {f}" for f in pack.risk_flags)
        overview_lines.append(f"⚠️ <b>위험 신호</b>\n{flags}\n")

    if pack.style_warnings:
        warns = "\n".join(f"  • {w}" for w in pack.style_warnings)
        overview_lines.append(f"🔄 <b>스타일 경고</b>\n{warns}\n")

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


def send_candidate_card_messages(card) -> list[dict]:
    """
    CandidateCard를 텔레그램 전송용 메시지 목록으로 변환합니다.

    Returns:
        [{"text": str, "hook_index": int | None}, ...]
        hook_index: None = 참조용(버튼 없음), 0~2 = 훅 후보(선택 버튼 있음)
    """
    messages: list[dict] = []

    # ── 1. 개요 카드 ──
    certainty_icon = {"확정": "✅", "미확인": "⚠️", "상충": "🔀"}.get(
        card.certainty_level, "❓"
    )
    overview_lines = [
        "📋 <b>후보 카드 생성 완료</b>\n",
        f"{certainty_icon} <b>확정 수준:</b> {card.certainty_level}\n",
    ]

    if card.topic_tags:
        tags = " ".join(f"#{t}" for t in card.topic_tags)
        overview_lines.append(f"🏷 {tags}\n")

    if card.risk_flags:
        flags = "\n".join(f"  • {f}" for f in card.risk_flags)
        overview_lines.append(f"⚠️ <b>위험 신호</b>\n{flags}\n")

    messages.append({"text": "\n".join(overview_lines), "hook_index": None})

    # ── 2. 핵심 팩트 ──
    if card.key_facts:
        facts_text = "📌 <b>핵심 팩트</b>\n\n"
        for i, fact in enumerate(card.key_facts, 1):
            facts_text += f"  {i}. {fact}\n"
        messages.append({"text": facts_text.strip(), "hook_index": None})

    # ── 3. 훅 후보 × 3 (선택 버튼 있음) ──
    for i, hook in enumerate(card.hook_candidates[:3]):
        label = ["A", "B", "C"][i]
        text = f"🎯 <b>훅 후보 {label}</b>\n\n<code>{hook}</code>"
        messages.append({"text": text, "hook_index": i})

    # ── 4. 한줄 결론 ──
    if card.one_liner:
        liner_text = "💡 <b>한줄 결론</b>\n\n"
        for j, ol in enumerate(card.one_liner, 1):
            liner_text += f"  {j}. {ol}\n"
        messages.append({"text": liner_text.strip(), "hook_index": None})

    # ── 5. 주의문 ──
    if card.cautions:
        caution_text = "🚨 <b>주의문</b>\n\n"
        for c in card.cautions:
            caution_text += f"  • {c}\n"
        messages.append({"text": caution_text.strip(), "hook_index": None})

    # ── 6. 관찰 포인트 ──
    if card.watch_points:
        watch_text = "👀 <b>지금 봐야 할 포인트</b>\n\n"
        for wp in card.watch_points:
            watch_text += f"  • {wp}\n"
        messages.append({"text": watch_text.strip(), "hook_index": None})

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
