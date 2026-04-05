"""
텔레그램 봇 핸들러
==================
전체 입력 → 분석 → 게시/댓글 선택 → 초안 생성 → 승인 워크플로를 처리합니다.

흐름:
  1. 사용자가 URL 또는 사진을 보냄
  2. 봇이 분석 (URL 스크래핑 / Claude Vision)
  3. Gemini 리서치 + Perplexity 팩트체크 병렬 실행
  4. 분석 결과 카드 + [📝 새 게시글] [💬 댓글로] [❌ 취소] 버튼
  5a. 새 게시글 선택 → AI 파이프라인 → 승인 카드
  5b. 댓글 선택 → "답글 달 트윗 URL 보내줘" → 입력 후 → AI 파이프라인 → 승인 카드
  6. Approve → X 게시

사용자 상태는 context.user_data에 저장합니다 (인메모리, 재시작 시 초기화).
"""

import asyncio
import json
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CallbackQueryHandler, CommandHandler,
    MessageHandler, ContextTypes, filters,
)
from app.config import settings
from app.services.telegram_service import parse_callback_data, send_analysis_card
from app.orchestrator import Orchestrator

logger = logging.getLogger(__name__)

# 사용자 상태 키
STATE_KEY = "state"
PENDING_KEY = "pending"

# 상태값
STATE_IDLE = "idle"
STATE_AWAITING_TYPE = "awaiting_type"
STATE_AWAITING_REPLY_TARGET = "awaiting_reply_target"


# =============================================================================
# 유틸
# =============================================================================

def _get_state(context: ContextTypes.DEFAULT_TYPE) -> str:
    return context.user_data.get(STATE_KEY, STATE_IDLE)


def _set_state(context: ContextTypes.DEFAULT_TYPE, state: str):
    context.user_data[STATE_KEY] = state


def _set_pending(context: ContextTypes.DEFAULT_TYPE, data: dict):
    context.user_data[PENDING_KEY] = data


def _get_pending(context: ContextTypes.DEFAULT_TYPE) -> dict | None:
    return context.user_data.get(PENDING_KEY)


def _clear(context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop(STATE_KEY, None)
    context.user_data.pop(PENDING_KEY, None)


# =============================================================================
# 공통 분석 파이프라인 (URL 또는 사진 모두 여기서 처리)
# =============================================================================

async def _run_analysis_and_show_card(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    title: str,
    text: str,
    source_url: str | None,
    content_type: str,
    source_type: str,
):
    """
    1. Gemini 리서치 + Perplexity 팩트체크 병렬 실행
    2. 분석 카드 전송 (게시글 / 댓글 / 취소 버튼 포함)
    """
    msg_id = str(update.message.message_id)

    # 분석 중 메시지
    status_msg = await update.message.reply_text("🔬 팩트 조사 중...")

    # Gemini & Perplexity 병렬 실행
    orchestrator = Orchestrator()
    try:
        research_task = orchestrator.ai.researcher.research(
            query=title, context=text[:1000]
        )
        factcheck_task = orchestrator.ai.fact_checker.check_facts(
            claim=text[:1000], context=title
        )
        research, factcheck = await asyncio.gather(
            research_task, factcheck_task, return_exceptions=True
        )
    finally:
        orchestrator.close()

    # 결과 정리
    research_summary = ""
    if not isinstance(research, Exception):
        facts = research.key_facts[:3]
        research_summary = research.summary[:300]
        if facts:
            research_summary += "\n• " + "\n• ".join(facts)

    factcheck_summary = ""
    if not isinstance(factcheck, Exception):
        status = "✅ 검증됨" if factcheck.verified else "⚠️ 미검증"
        confidence = factcheck.confidence
        factcheck_summary = f"{status} (신뢰도: {confidence})"
        if factcheck.corrections:
            factcheck_summary += "\n수정사항: " + "; ".join(factcheck.corrections[:2])

    # 상태 저장
    _set_pending(context, {
        "title": title,
        "text": text,
        "url": source_url,
        "source_type": source_type,
        "content_type": content_type,
        "research_summary": research_summary,
        "factcheck_summary": factcheck_summary,
        "msg_id": msg_id,
    })
    _set_state(context, STATE_AWAITING_TYPE)

    # 분석 카드 전송
    card_text = (
        f"🔍 <b>분석 완료</b>\n"
        f"{'─' * 28}\n\n"
        f"📰 <b>{title[:150]}</b>\n\n"
        f"📋 유형: {content_type}\n"
    )
    if research_summary:
        card_text += f"\n🔬 <b>핵심 내용:</b>\n{research_summary[:350]}\n"
    if factcheck_summary:
        card_text += f"\n{factcheck_summary}\n"
    card_text += f"\n{'─' * 28}\n<b>어떻게 사용할까요?</b>"

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📝 새 게시글", callback_data=f"type_tweet:{msg_id}"),
            InlineKeyboardButton("💬 댓글로", callback_data=f"type_reply:{msg_id}"),
        ],
        [
            InlineKeyboardButton("📦 콘텐츠 팩", callback_data=f"type_pack:{msg_id}"),
            InlineKeyboardButton("❌ 취소", callback_data=f"type_cancel:{msg_id}"),
        ],
    ])

    await status_msg.delete()
    await update.message.reply_text(card_text, parse_mode="HTML", reply_markup=keyboard)


# =============================================================================
# 메시지 핸들러 — URL 텍스트
# =============================================================================

async def url_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """사용자가 URL을 보낸 경우."""
    from app.services.content_fetcher import fetch_url_content, is_x_url

    url = update.message.text.strip()
    logger.info(f"URL 수신: {url[:80]}")

    # X/Twitter URL은 댓글 대상으로만 사용 가능 — 안내
    if is_x_url(url) and _get_state(context) != STATE_AWAITING_REPLY_TARGET:
        await update.message.reply_text(
            "🐦 X(Twitter) 링크를 받았어요.\n\n"
            "이 링크에 <b>댓글</b>을 달려면:\n"
            "① 먼저 분석할 뉴스 링크나 사진을 보내고\n"
            "② [💬 댓글로] 선택 후 이 URL을 보내주세요.",
            parse_mode="HTML",
        )
        return

    # 스레드 생성 대기 중
    if _get_state(context) == STATE_AWAITING_THREAD_INPUT:
        await _generate_and_send_thread(update, context, url)
        return

    # 댓글 대상 URL 입력 대기 중
    if _get_state(context) == STATE_AWAITING_REPLY_TARGET:
        await _handle_reply_target_url(update, context, url)
        return

    status_msg = await update.message.reply_text("🔍 기사 분석 중...")

    result = await fetch_url_content(url)

    # 수집 전략 표시
    source_label = {
        "direct": "직접 수집",
        "jina": "Jina AI Reader",
        "google_cache": "Google 캐시",
        "failed": None,
    }.get(result.get("source", ""), "")

    if result.get("source") == "failed" or not result["text"]:
        await status_msg.edit_text(
            "⚠️ <b>URL 콘텐츠를 읽을 수 없습니다</b>\n\n"
            "3가지 방법을 모두 시도했지만 실패했습니다:\n"
            "① 직접 접근 → 차단\n"
            "② Jina AI Reader → 실패\n"
            "③ Google 캐시 → 없음\n\n"
            "📋 <b>해결 방법:</b>\n"
            "기사 본문 텍스트를 복사해서 직접 붙여넣어 주세요.\n"
            "제목 + 주요 내용 몇 문단이면 충분합니다.",
            parse_mode="HTML",
        )
        return

    if source_label and source_label != "직접 수집":
        await status_msg.edit_text(f"🔍 기사 분석 중... ({source_label}로 수집)")

    # 뉴스 기사 = manual (팩트 기반)
    await _run_analysis_and_show_card(
        update, context,
        title=result["title"],
        text=result["text"],
        source_url=url,
        content_type="뉴스기사",
        source_type="manual",
    )


async def text_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """사용자가 일반 텍스트(커뮤 복붙 등)를 보낸 경우."""
    text = update.message.text.strip()
    logger.info(f"텍스트 수신: {text[:60]}")

    # 스레드 생성 대기 중
    if _get_state(context) == STATE_AWAITING_THREAD_INPUT:
        await _generate_and_send_thread(update, context, text)
        return

    # 댓글 대상 URL 대기 중인데 URL 아닌 텍스트가 오면 안내
    if _get_state(context) == STATE_AWAITING_REPLY_TARGET:
        await update.message.reply_text(
            "⚠️ X 트윗 URL이 필요해요.\n"
            "예: https://x.com/user/status/1234567890\n\n"
            "취소하려면 /cancel"
        )
        return

    title = text[:80] + ("..." if len(text) > 80 else "")
    # 텍스트 직접 입력 = 커뮤니티 입력으로 처리
    await _run_analysis_and_show_card(
        update, context,
        title=title,
        text=text,
        source_url=None,
        content_type="직접입력/커뮤",
        source_type="community_input",
    )


# =============================================================================
# 메시지 핸들러 — 사진
# =============================================================================

async def photo_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """사용자가 사진/스크린샷을 보낸 경우."""
    from app.services.vision_service import extract_from_image

    logger.info("사진 수신 — Claude Vision으로 분석 시작")
    status_msg = await update.message.reply_text("🖼️ 사진 분석 중...")

    # 가장 큰 해상도 선택
    photo = update.message.photo[-1]
    try:
        file = await context.bot.get_file(photo.file_id)
        image_bytes = await file.download_as_bytearray()
    except Exception as e:
        await status_msg.edit_text(f"⚠️ 사진 다운로드 실패: {e}")
        return

    vision_result = await extract_from_image(bytes(image_bytes), mime_type="image/jpeg")

    if vision_result.get("error") == "anthropic_key_missing":
        await status_msg.edit_text(
            "⚠️ 이미지 분석 불가 (Anthropic API 키 없음)\n"
            "텍스트로 내용을 직접 붙여넣어 주세요."
        )
        return

    await status_msg.delete()

    # 사진 = 커뮤니티 입력으로 처리
    await _run_analysis_and_show_card(
        update, context,
        title=vision_result["title"],
        text=vision_result["text"],
        source_url=None,
        content_type=vision_result.get("content_type", "이미지"),
        source_type="community_input",
    )


# =============================================================================
# 댓글 대상 URL 처리
# =============================================================================

async def _handle_reply_target_url(
    update: Update, context: ContextTypes.DEFAULT_TYPE, url: str
):
    """'댓글로' 선택 후 사용자가 보낸 트윗 URL 처리."""
    from app.services.content_fetcher import extract_tweet_id, is_x_url

    if not is_x_url(url):
        await update.message.reply_text(
            "⚠️ X 트윗 URL이 아닌 것 같아요.\n"
            "예: https://x.com/user/status/1234567890\n\n"
            "취소하려면 /cancel"
        )
        return

    tweet_id = extract_tweet_id(url)
    if not tweet_id:
        await update.message.reply_text(
            "⚠️ 트윗 ID를 찾을 수 없어요.\n"
            "URL 형식을 확인해주세요: https://x.com/.../status/[트윗ID]"
        )
        return

    pending = _get_pending(context)
    if not pending:
        await update.message.reply_text("⚠️ 세션 만료. 다시 처음부터 시작해주세요.")
        _clear(context)
        return

    await update.message.reply_text(f"🔄 댓글 초안 생성 중 (답글→{tweet_id[:20]})...")

    # 파이프라인 실행 (reply 모드)
    await _run_pipeline(
        update, context,
        pending=pending,
        post_mode="reply",
        reply_to_tweet_id=tweet_id,
    )


# =============================================================================
# AI 파이프라인 실행 공통 함수
# =============================================================================

async def _run_pipeline(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    pending: dict,
    post_mode: str,               # "tweet" | "reply"
    reply_to_tweet_id: str | None = None,
):
    """
    pending 데이터를 이용해 AI 파이프라인을 실행하고 승인 카드를 전송합니다.
    """
    from app.models.content import SourceItemCreate

    source_data = SourceItemCreate(
        title=pending["title"],
        url=pending.get("url"),
        source_text=pending["text"],
        source_type=pending["source_type"],
        language="ko",
    )

    orchestrator = Orchestrator()
    try:
        draft = await orchestrator.ingest_and_generate(source_data)

        # 댓글 모드: reply_to_tweet_id 저장
        if post_mode == "reply" and reply_to_tweet_id:
            draft.reply_to_tweet_id = reply_to_tweet_id
            orchestrator.db.commit()

        await orchestrator.send_for_approval(draft.id)

        mode_label = "📝 새 게시글" if post_mode == "tweet" else f"💬 댓글 (→{reply_to_tweet_id})"
        await update.message.reply_text(
            f"✅ <b>초안 생성 완료!</b>\n"
            f"모드: {mode_label}\n"
            f"Draft ID: {draft.id}\n\n"
            f"텔레그램으로 승인 카드가 전송됐어요.",
            parse_mode="HTML",
        )
    except Exception as e:
        logger.error(f"파이프라인 오류: {e}", exc_info=True)
        await update.message.reply_text(f"❌ 오류: {str(e)[:300]}")
    finally:
        orchestrator.close()
        _clear(context)


# =============================================================================
# 콜백 핸들러 (인라인 버튼 응답)
# =============================================================================

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    모든 인라인 버튼 콜백을 처리합니다.

    처리하는 callback_data 형식:
      type_tweet:{msg_id}    — 새 게시글 선택
      type_reply:{msg_id}    — 댓글로 선택
      type_cancel:{msg_id}   — 취소
      approve:{draft_id}     — 초안 승인
      reject:{draft_id}      — 초안 거절
      defer:{draft_id}       — 초안 보류
      regenerate:{draft_id}  — 초안 재생성
    """
    query = update.callback_query
    await query.answer()

    callback_data = query.data
    logger.info(f"콜백 수신: {callback_data}")

    # --- 뉴스 모니터 알림 콜백 ---
    if callback_data.startswith("news_"):
        await _handle_news_callback(query, context)
        return

    # --- 콘텐츠 팩 선택 콜백 ---
    if callback_data.startswith("pack_select:"):
        await _handle_pack_select_callback(query, context)
        return

    # --- 타입 선택 콜백 ---
    if callback_data.startswith("type_"):
        await _handle_type_callback(query, context)
        return

    # --- 기존 승인/거절 콜백 ---
    parsed = parse_callback_data(callback_data)
    if not parsed:
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text("⚠️ 잘못된 요청입니다.")
        return

    action, draft_id = parsed
    await query.edit_message_reply_markup(reply_markup=None)

    orchestrator = Orchestrator()
    try:
        result = await orchestrator.handle_approval(draft_id, action)

        if result.get("success"):
            if action == "approve" and result.get("x_post_id"):
                reply_label = ""
                from app.db import get_db
                from app.services.draft_service import DraftService
                db = get_db()
                try:
                    d = DraftService(db).get_by_id(draft_id)
                    if d and getattr(d, "reply_to_tweet_id", None):
                        reply_label = f"\n💬 답글 대상: {d.reply_to_tweet_id}"
                finally:
                    db.close()

                response_text = (
                    f"✅ <b>X 게시 완료!</b>{reply_label}\n\n"
                    f"Post ID: {result['x_post_id']}\n"
                    f"URL: {result.get('x_post_url', 'N/A')}"
                )
            else:
                response_text = f"✅ {result.get('message', 'Done!')}"
        else:
            response_text = f"⚠️ {result.get('error', '오류 발생')}"

        await query.message.reply_text(response_text, parse_mode="HTML")

    except Exception as e:
        logger.error(f"콜백 처리 오류: {e}", exc_info=True)
        await query.message.reply_text(f"❌ 오류: {str(e)[:200]}")
    finally:
        orchestrator.close()


async def _handle_news_callback(query, context: ContextTypes.DEFAULT_TYPE):
    """
    뉴스 모니터 속보 알림 버튼 처리.
    news_draft:{hash} → AI 파이프라인 → 초안 텍스트 Telegram 전달
    news_skip:{hash}  → 무시
    """
    from app.services.news_monitor import get_pending_article, remove_pending_article

    data = query.data  # "news_draft:abc123" or "news_skip:abc123"
    parts = data.split(":", 1)
    if len(parts) != 2:
        await query.edit_message_reply_markup(reply_markup=None)
        return

    action, article_hash = parts[0], parts[1]
    await query.edit_message_reply_markup(reply_markup=None)

    if action == "news_skip":
        remove_pending_article(article_hash)
        await query.message.reply_text("⏭ 스킵됐어요.")
        return

    if action == "news_regen":
        # 재생성 — news_draft와 동일한 로직 재실행
        action = "news_draft"

    # news_draft
    article = get_pending_article(article_hash)
    if not article:
        await query.message.reply_text("⚠️ 기사 정보 만료. 다시 링크를 보내주세요.")
        return

    await query.message.reply_text(
        f"✍️ <b>초안 작성 중...</b>\n📰 {article['title'][:80]}",
        parse_mode="HTML",
    )

    try:
        from app.models.content import SourceItemCreate
        from app.services.content_fetcher import fetch_url_content
        from app.services.quality_scorer import score_draft, should_regenerate, format_score_report

        # 기사 본문 수집
        fetched = await fetch_url_content(article["url"])
        source_text = fetched["text"] if fetched["text"] else article.get("summary", article["title"])

        source_data = SourceItemCreate(
            title=article["title"],
            url=article["url"],
            source_text=source_text,
            source_type="manual",
            language="ko",
        )

        orchestrator = Orchestrator()
        try:
            draft = await orchestrator.ingest_and_generate(source_data)

            # 품질 점수 체크 → 미달 시 1회 재생성
            score, reasons = score_draft(
                type("D", (), {"hook": draft.hook, "body": draft.body})(),
                source_type="manual",
            )
            if should_regenerate(score):
                logger.info(f"품질 미달({score}점) → 재생성")
                new_draft = await orchestrator.ingest_and_generate(source_data)
                new_score, _ = score_draft(
                    type("D", (), {"hook": new_draft.hook, "body": new_draft.body})(),
                )
                if new_score >= score:
                    draft = new_draft
                    score = new_score

        finally:
            orchestrator.close()

        remove_pending_article(article_hash)

        # 초안 텍스트 전달 (자동 게시 없음 — 사용자가 직접 X에 붙여넣기)
        draft_text = f"{draft.hook}\n\n{draft.body}"
        if draft.thread_continuation:
            draft_text += f"\n\n🧵 {draft.thread_continuation}"

        score_line = f"📊 품질: {score}/100"

        reply = (
            f"📝 <b>초안 완성!</b> {score_line}\n"
            f"{'─' * 28}\n"
            f"{draft_text}\n"
            f"{'─' * 28}\n"
            f"📋 {draft.category.value} | {draft.risk_level.value.upper()}\n\n"
            f"위 텍스트를 복사해서 X에 붙여넣기 해주세요."
        )

        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("🔄 재생성", callback_data=f"news_regen:{article_hash}"),
        ]])

        # 재생성용으로 기사 정보 유지
        await query.message.reply_text(reply, parse_mode="HTML", reply_markup=keyboard)

    except Exception as e:
        logger.error(f"뉴스 초안 생성 오류: {e}", exc_info=True)
        await query.message.reply_text(f"❌ 초안 생성 실패: {str(e)[:200]}")


async def _handle_type_callback(query, context: ContextTypes.DEFAULT_TYPE):
    """[게시글 / 댓글 / 취소] 버튼 처리."""
    data = query.data  # type_tweet:123 / type_reply:123 / type_cancel:123
    parts = data.split(":", 1)
    if len(parts) != 2:
        await query.edit_message_reply_markup(reply_markup=None)
        return

    action, msg_id = parts[0], parts[1]

    # 버튼 제거
    await query.edit_message_reply_markup(reply_markup=None)

    if action == "type_cancel":
        _clear(context)
        await query.message.reply_text("❌ 취소됐어요. 새 링크나 사진을 보내주세요.")
        return

    pending = _get_pending(context)
    if not pending or pending.get("msg_id") != msg_id:
        await query.message.reply_text("⚠️ 세션 만료. 다시 처음부터 시작해주세요.")
        _clear(context)
        return

    if action == "type_tweet":
        await query.message.reply_text("🔄 게시글 초안 생성 중...")
        await _run_pipeline(
            type("FakeUpdate", (), {"message": query.message})(),
            context,
            pending=pending,
            post_mode="tweet",
        )

    elif action == "type_reply":
        _set_state(context, STATE_AWAITING_REPLY_TARGET)
        await query.message.reply_text(
            "💬 <b>답글 달 트윗 URL을 보내줘</b>\n\n"
            "예: <code>https://x.com/user/status/1234567890</code>\n\n"
            "취소: /cancel",
            parse_mode="HTML",
        )

    elif action == "type_pack":
        await _run_content_pack(
            type("FakeUpdate", (), {"message": query.message})(),
            context,
            pending=pending,
        )


# =============================================================================
# 커맨드 핸들러
# =============================================================================

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/start"""
    await update.message.reply_text(
        "🇰🇷 <b>X Posting System — @cheesesvav</b>\n"
        "<i>Beyond headlines: how Korea really works, feels, and changes.</i>\n\n"
        "<b>기본 사용법:</b>\n"
        "1️⃣ 뉴스 URL · 스크린샷 · 텍스트 전송\n"
        "2️⃣ 분석 카드에서 원하는 모드 선택\n"
        "   • [📝 새 게시글] — 단일 포스트 → 승인 후 X 게시\n"
        "   • [📦 콘텐츠 팩] — 메인 3개+댓글+인용+짧은버전 일괄 생성\n"
        "   • [💬 댓글로] — 특정 트윗에 답글\n\n"
        "<b>Commands:</b>\n"
        "/pack [url/text] — 콘텐츠 팩 직접 생성 📦\n"
        "/thread — 스레드 생성 🧵\n"
        "/trends — 트렌드 탐색\n"
        "/queue — 게시 큐\n"
        "/hunt — 댓글 기회 탐색\n"
        "/note &lt;id&gt; &lt;메모&gt; — 초안에 메모 추가 (최대 500자)\n"
        "/hint &lt;id&gt; &lt;메모&gt; — 장기 힌트 저장 (다음 초안 작성에 반영)\n"
        "/perf &lt;id&gt; &lt;메모&gt; — 게시 후 성과 메모 기록\n"
        "/perf — 최근 성과 메모 목록\n"
        "/status — AI 상태\n"
        "/pending — 대기 초안\n"
        "/cancel — 취소\n",
        parse_mode="HTML",
    )


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/cancel — 현재 상태 초기화"""
    state = _get_state(context)
    if state == STATE_IDLE:
        await update.message.reply_text("취소할 작업이 없어요.")
    else:
        _clear(context)
        await update.message.reply_text("✅ 취소됐어요. 새 링크나 사진을 보내주세요.")


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/status"""
    ai_status = settings.ai_status_summary()
    lines = [f"  {k}: {v}" for k, v in ai_status.items()]
    text = (
        "📊 <b>System Status</b>\n\n"
        + "\n".join(lines)
        + f"\n\nAuto-post: {'ON ⚠️' if settings.enable_auto_post_low_risk else 'OFF ✅'}"
    )
    await update.message.reply_text(text, parse_mode="HTML")


async def pending_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/pending"""
    from app.db import get_db
    from app.services.draft_service import DraftService

    db = get_db()
    try:
        drafts = DraftService(db).get_pending()
        if not drafts:
            await update.message.reply_text("📭 대기 중인 초안이 없습니다.")
            return
        text = "📋 <b>Pending Drafts</b>\n\n"
        for d in drafts[:10]:
            reply_note = f" 💬→{d.reply_to_tweet_id}" if getattr(d, "reply_to_tweet_id", None) else ""
            text += (
                f"• ID {d.id}{reply_note}: {d.hook[:50]}...\n"
                f"  [{d.category.value}] [{d.risk_level.value}]\n\n"
            )
        await update.message.reply_text(text, parse_mode="HTML")
    finally:
        db.close()


async def trends_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/trends [topic]"""
    topic = " ".join(context.args) if context.args else "korea"
    await update.message.reply_text(f"🔍 트렌드 탐색 중: {topic}...")

    orchestrator = Orchestrator()
    try:
        result = await orchestrator.get_trending_topics(topic)
        if result.get("success") and result.get("topics"):
            text = f"📈 <b>Trending ({topic})</b>\n\n"
            for i, t in enumerate(result["topics"][:10], 1):
                text += f"{i}. {t}\n"
            if result.get("notes"):
                text += f"\n💡 {result['notes'][:200]}"
            await update.message.reply_text(text, parse_mode="HTML")
        elif result.get("success"):
            await update.message.reply_text("📭 현재 감지된 트렌드가 없습니다.")
        else:
            await update.message.reply_text(f"⚠️ {result.get('error', 'Unknown')[:200]}")
    except Exception as e:
        await update.message.reply_text(f"❌ 오류: {str(e)[:200]}")
    finally:
        orchestrator.close()


# =============================================================================
# /thread 커맨드 — 스레드 생성기
# =============================================================================

# 스레드 대기 상태
STATE_AWAITING_THREAD_INPUT = "awaiting_thread_input"


async def thread_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/thread — 뉴스 링크 또는 텍스트로 5~7 트윗 스레드 생성"""
    # 인수로 직접 입력한 경우 (예: /thread https://...)
    if context.args:
        source = " ".join(context.args)
        await _generate_and_send_thread(update, context, source)
    else:
        _set_state(context, STATE_AWAITING_THREAD_INPUT)
        await update.message.reply_text(
            "🧵 <b>스레드 생성</b>\n\n"
            "스레드로 만들 뉴스 링크 또는 내용을 보내주세요.\n"
            "예: https://news.com/article\n\n"
            "/cancel 로 취소",
            parse_mode="HTML",
        )


async def _generate_and_send_thread(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    source: str,
    num_tweets: int = 5,
) -> None:
    """소스 텍스트/URL → 스레드 생성 → Telegram 전송."""
    _clear(context)
    msg = await update.message.reply_text("🧵 스레드 생성 중... (잠시만요)")

    try:
        # URL이면 콘텐츠 fetch
        from app.services.content_fetcher import is_url, fetch_url_content
        if is_url(source):
            fetched = await fetch_url_content(source)
            title = fetched.get("title", source[:80])
            body  = fetched.get("text", "")[:2500]
        else:
            title = source[:80]
            body  = source[:2500]

        # AI 스레드 생성
        provider_name = settings.get_effective_draft_provider()
        if provider_name == "openai" and settings.has_openai:
            from app.providers.openai_provider import OpenAIDraftWriter
            writer = OpenAIDraftWriter()
            result = await writer.generate_thread(title, body, num_tweets=num_tweets)
        elif provider_name == "anthropic" and settings.has_anthropic:
            from app.providers.anthropic_provider import AnthropicDraftWriter
            writer = AnthropicDraftWriter()
            result = await writer.generate_thread(title, body, num_tweets=num_tweets)
        else:
            # Mock
            from app.providers.openai_provider import ThreadResult
            result = ThreadResult(
                tweets=[
                    f"[MOCK] Hook: {title[:80]}",
                    "[MOCK] The key fact with a specific number.",
                    "[MOCK] Your take — one opinion, no hedging.",
                    "[MOCK] In Korean forums, the reaction is...",
                    "[MOCK] Global impact + Follow for more Korea signal.",
                ],
                content_pillar="economy",
                optimal_post_time="09:00 EST",
            )

        # 스레드 포맷 전송
        pillar_emoji = {"economy": "📈", "crypto": "🪙", "geopolitics": "🌏", "community": "💬"}.get(
            result.content_pillar, "📰"
        )
        header = (
            f"🧵 <b>스레드 생성 완료</b> ({result.tweet_count}개 트윗)\n"
            f"{pillar_emoji} {result.content_pillar.upper()} | "
            f"📅 최적 게시: {result.optimal_post_time}\n"
            f"{'─' * 28}\n\n"
        )

        thread_text = result.format_for_telegram()

        full_msg = header + thread_text
        # 4096자 초과 시 분할 전송
        if len(full_msg) <= 4000:
            await msg.edit_text(full_msg, parse_mode="HTML")
        else:
            await msg.edit_text(header + "트윗 목록:", parse_mode="HTML")
            for i, tweet in enumerate(result.tweets, 1):
                await update.message.reply_text(
                    f"[{i}/{result.tweet_count}]\n{tweet}",
                )

        # tone notes
        if result.tone_notes:
            await update.message.reply_text(
                f"💡 <i>{result.tone_notes[:200]}</i>", parse_mode="HTML"
            )

    except Exception as e:
        logger.error(f"스레드 생성 오류: {e}")
        await msg.edit_text(f"❌ 스레드 생성 실패: {str(e)[:200]}")


# =============================================================================
# 콘텐츠 팩 파이프라인
# =============================================================================

# user_data 키
CONTENT_PACK_KEY = "content_pack"


async def _run_content_pack(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    pending: dict | None = None,
    source_override: str | None = None,
) -> None:
    """
    ContentRequest → ContentPack 생성 → Telegram 멀티 메시지 전송.
    기존 단일 포스트 승인 파이프라인과 완전히 병렬로 동작합니다.
    """
    from app.models.content_request import ContentRequest
    from app.services.content_pack import generate_content_pack
    from app.services.repetition_guard import RepetitionGuard
    from app.services.telegram_service import send_content_pack_messages
    from app.db import get_db
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    _clear(context)
    msg = await update.message.reply_text("📦 <b>콘텐츠 팩 생성 중...</b>", parse_mode="HTML")

    try:
        # 입력 정규화
        if source_override:
            # /pack <text or url>
            from app.services.content_fetcher import is_url
            if is_url(source_override):
                from app.services.content_fetcher import fetch_url_content
                fetched = await fetch_url_content(source_override)
                req = ContentRequest(
                    source_url=source_override,
                    source_type="news_link",
                    raw_text=fetched.get("text", ""),
                    note=None,
                )
            else:
                req = ContentRequest(
                    source_type="raw_text",
                    raw_text=source_override,
                )
        elif pending:
            # 분석 카드에서 "콘텐츠 팩" 버튼 → pending에 이미 수집된 데이터 사용
            fetched_text = pending.get("fetched_text", "") or pending.get("source_text", "")
            req = ContentRequest(
                source_url=pending.get("url"),
                source_type="news_link" if pending.get("url") else "raw_text",
                raw_text=fetched_text,
                note=pending.get("note"),
            )
        else:
            await msg.edit_text("⚠️ 소스 정보 없음. URL이나 텍스트를 보내주세요.")
            return

        if not req.has_content():
            await msg.edit_text("⚠️ 콘텐츠 내용이 부족합니다. 텍스트나 URL을 함께 보내주세요.")
            return

        # 팩 생성
        pack = await generate_content_pack(req)

        # 반복 경고 주입
        try:
            db = get_db()
            try:
                guard = RepetitionGuard(db)
                extra_warnings = guard.check_pack(pack)
                pack.style_warnings = (pack.style_warnings or []) + extra_warnings
            finally:
                db.close()
        except Exception as e:
            logger.warning(f"RepetitionGuard 실패 (무시): {e}")

        # user_data에 팩 저장 (pack_select 콜백에서 참조)
        context.user_data[CONTENT_PACK_KEY] = pack

        await msg.delete()

        # 멀티 메시지 전송
        pack_messages = send_content_pack_messages(pack)
        for pm in pack_messages:
            text = pm["text"][:4096]  # Telegram 메시지 최대 길이
            pack_index = pm.get("pack_index")

            if pack_index is not None:
                # 승인 가능한 항목 → "이걸로 승인 큐에 추가" 버튼
                keyboard = InlineKeyboardMarkup([[
                    InlineKeyboardButton(
                        "✅ 승인 큐에 추가",
                        callback_data=f"pack_select:{pack_index}",
                    )
                ]])
                await update.message.reply_text(text, parse_mode="HTML", reply_markup=keyboard)
            else:
                await update.message.reply_text(text, parse_mode="HTML")

    except Exception as e:
        logger.error(f"콘텐츠 팩 생성 오류: {e}", exc_info=True)
        await msg.edit_text(f"❌ 콘텐츠 팩 생성 실패: {str(e)[:200]}")


async def _handle_pack_select_callback(
    query, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    pack_select:{index} 콜백 처리.
    선택된 포스트를 DB Draft로 저장하고 기존 승인 카드 전송.
    """
    parts = query.data.split(":", 1)
    if len(parts) != 2:
        await query.edit_message_reply_markup(reply_markup=None)
        return

    try:
        pack_index = int(parts[1])
    except ValueError:
        await query.edit_message_reply_markup(reply_markup=None)
        return

    await query.edit_message_reply_markup(reply_markup=None)

    pack = context.user_data.get(CONTENT_PACK_KEY)
    if not pack:
        await query.message.reply_text("⚠️ 팩 정보 만료. /pack 으로 다시 생성해주세요.")
        return

    # 인덱스 → 텍스트 추출
    if pack_index == 10:
        post_text = pack.short_version
    elif 0 <= pack_index < len(pack.main_posts):
        post_text = pack.main_posts[pack_index]
    else:
        await query.message.reply_text("⚠️ 잘못된 인덱스. 팩을 다시 생성해주세요.")
        return

    if not post_text:
        await query.message.reply_text("⚠️ 선택된 포스트 내용이 비어 있습니다.")
        return

    # hook + body 분리 (첫 줄 = hook, 나머지 = body)
    lines = post_text.strip().splitlines()
    hook = lines[0].strip()
    body = "\n".join(lines[1:]).strip() if len(lines) > 1 else hook

    await query.message.reply_text(
        f"✅ <b>승인 큐에 추가됨</b>\n\n<code>{post_text[:300]}</code>\n\n"
        f"<i>기존 승인 카드로 처리됩니다.</i>",
        parse_mode="HTML",
    )

    # 기존 파이프라인으로 넘기기 — SourceItemCreate 생성 후 ingest
    try:
        from app.models.content import SourceItemCreate
        from app.orchestrator import Orchestrator
        import json

        source_data = SourceItemCreate(
            title=hook[:200],
            url=pack.source_url or "",
            source_text=post_text,
            source_type="manual",
            language="english",
        )

        orchestrator = Orchestrator()
        try:
            draft = await orchestrator.ingest_and_generate(source_data)
            # 팩 메타 기록
            if draft and hasattr(draft, "id"):
                from app.db import get_db
                db = get_db()
                try:
                    from app.models.content import Draft
                    db_draft = db.query(Draft).filter(Draft.id == draft.id).first()
                    if db_draft:
                        db_draft.content_type = pack.source_type
                        db_draft.topic_tags = json.dumps(pack.topic_tags or [])
                        db_draft.output_format = "pack"
                        db.commit()
                finally:
                    db.close()
        finally:
            orchestrator.close()
    except Exception as e:
        logger.error(f"팩 선택 → 파이프라인 오류: {e}", exc_info=True)
        await query.message.reply_text(
            f"⚠️ 승인 카드 생성 중 오류: {str(e)[:200]}\n"
            "텍스트를 직접 복사해서 X에 게시할 수 있습니다.",
        )


async def pack_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/pack [url or text] — 콘텐츠 팩 직접 생성."""
    args_text = " ".join(context.args).strip() if context.args else ""

    if args_text:
        await _run_content_pack(update, context, source_override=args_text)
    else:
        await update.message.reply_text(
            "📦 <b>콘텐츠 팩 생성</b>\n\n"
            "사용법:\n"
            "• <code>/pack https://뉴스URL</code>\n"
            "• <code>/pack 한국은행 기준금리 2.75%로 동결. 수출 둔화 우려.</code>\n\n"
            "또는 URL이나 텍스트를 보내면 분석 카드에서 [📦 콘텐츠 팩] 버튼을 누르세요.",
            parse_mode="HTML",
        )


# =============================================================================
# Growth 파이프라인 커맨드
# =============================================================================

async def queue_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/queue — 게시 큐 현황 조회 또는 항목 추가.

    /queue          → 큐 목록 표시
    /queue <본문>   → 큐에 추가
    """
    from app.services.growth.post_queue import get_post_queue

    args_text = " ".join(context.args).strip() if context.args else ""

    queue = get_post_queue()

    if args_text:
        # 큐에 추가
        post = queue.add(args_text)
        pending_count = queue.count_pending()
        from datetime import datetime, timezone, timedelta
        added_kst = (post.added_at + timedelta(hours=9)).strftime("%H:%M KST")
        await update.message.reply_text(
            f"✅ <b>큐에 추가됨</b>\n\n"
            f"<code>{post.text[:200]}</code>\n\n"
            f"📋 대기 중: {pending_count}개\n"
            f"🕐 등록 시각: {added_kst}\n\n"
            f"<i>최적 슬롯(9:00/10:30/12:00/13:30/15:00/19:00/21:00 KST)에 자동 발행됩니다.</i>",
            parse_mode="HTML",
        )
        return

    # 큐 목록 표시
    pending = queue.list_pending()
    if not pending:
        await update.message.reply_text(
            "📋 <b>게시 큐가 비어 있습니다.</b>\n\n"
            "추가하려면:\n<code>/queue 게시할 본문 내용</code>",
            parse_mode="HTML",
        )
        return

    from datetime import timedelta
    lines = []
    for i, p in enumerate(pending[:10], 1):
        added_kst = (p.added_at + timedelta(hours=9)).strftime("%m/%d %H:%M")
        lines.append(f"{i}. [{added_kst}] {p.text[:60]}{'…' if len(p.text) > 60 else ''}")

    msg = (
        f"📋 <b>게시 큐 ({len(pending)}개 대기)</b>\n\n"
        + "\n".join(lines)
        + "\n\n<i>최적 슬롯에 순서대로 자동 발행됩니다.</i>"
    )
    await update.message.reply_text(msg, parse_mode="HTML")


async def hunt_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/hunt — CommentHunter로 댓글 기회 탐색."""
    from app.services.growth.comment_hunter import CommentHunter, generate_reply_draft

    msg = await update.message.reply_text("🔍 <b>댓글 기회 탐색 중...</b>", parse_mode="HTML")

    try:
        hunter = CommentHunter()
        targets = await hunter.hunt(max_results=5)

        if not targets:
            await msg.edit_text("🔍 현재 댓글 기회가 없습니다. 나중에 다시 시도해주세요.")
            return

        await msg.edit_text(f"✅ <b>댓글 기회 {len(targets)}건 발견</b>", parse_mode="HTML")

        for target in targets:
            # 초안이 아직 없으면 생성
            if not target.reply_draft:
                try:
                    target.reply_draft = await generate_reply_draft(target)
                except Exception:
                    target.reply_draft = "(초안 생성 실패)"

            await update.message.reply_text(
                target.format_for_telegram(),
                parse_mode="Markdown",
                disable_web_page_preview=True,
            )

    except Exception as e:
        logger.error(f"/hunt 오류: {e}", exc_info=True)
        await msg.edit_text(f"❌ 탐색 실패: {str(e)[:200]}")


async def report_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/report — 주간 성과 리포트 즉시 생성."""
    from app.services.growth.weekly_report import WeeklyReporter

    msg = await update.message.reply_text("📊 <b>주간 리포트 생성 중...</b>", parse_mode="HTML")

    try:
        reporter = WeeklyReporter()
        metrics = await reporter.collect()
        ai_tips = await reporter.analyze_with_ai(metrics)
        report_text = metrics.format_for_telegram()

        # Layer 2: 성과 메모 요약 (실패 시 무시)
        perf_section = ""
        try:
            db = get_db()
            from app.services.draft_service import DraftService
            perf_section = DraftService(db).format_perf_summary(days=30)
            if perf_section:
                perf_section = f"\n\n{perf_section}"
        except Exception:
            pass

        full_msg = f"{report_text}{perf_section}\n\n<b>🤖 다음 주 개선 포인트</b>\n{ai_tips}"

        await msg.delete()
        await update.message.reply_text(full_msg, parse_mode="HTML")

    except Exception as e:
        logger.error(f"/report 오류: {e}", exc_info=True)
        await msg.edit_text(f"❌ 리포트 생성 실패: {str(e)[:200]}")


async def digest_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/digest — 모닝 다이제스트 즉시 생성."""
    from app.services.morning_digest import run_morning_digest

    msg = await update.message.reply_text("📰 <b>다이제스트 생성 중...</b>", parse_mode="HTML")

    try:
        await run_morning_digest()
        await msg.edit_text("✅ 다이제스트를 생성하여 전송했습니다.")
    except Exception as e:
        logger.error(f"/digest 오류: {e}", exc_info=True)
        await msg.edit_text(f"❌ 다이제스트 생성 실패: {str(e)[:200]}")


async def perf_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/perf [draft_id] [메모] — 게시 후 성과 메모 추가. 인수 없으면 최근 목록 표시."""
    args = context.args or []

    if not args:
        # /perf 단독 → 최근 게시 + PERF 메모 목록
        try:
            db = get_db()
            from app.services.draft_service import DraftService
            drafts = DraftService(db).get_published_with_perf_notes(limit=5)
            if not drafts:
                await update.message.reply_text(
                    "아직 성과 메모가 없습니다.\n"
                    "<code>/perf &lt;draft_id&gt; &lt;메모&gt;</code> 로 추가하세요.",
                    parse_mode="HTML",
                )
                return
            lines = ["📊 <b>최근 성과 메모</b>\n"]
            for d in drafts:
                perf_lines = [
                    ln for ln in (d.manual_notes or "").splitlines()
                    if ln.startswith("[PERF]")
                ]
                perf_text = perf_lines[-1][7:].strip() if perf_lines else ""
                lines.append(
                    f"• ID {d.id} [{d.category.value}] "
                    f"{(d.hook or '')[:40]}…\n"
                    f"  └ {perf_text[:100]}"
                )
            await update.message.reply_text("\n".join(lines), parse_mode="HTML")
        except Exception as e:
            logger.error(f"/perf 목록 조회 오류: {e}", exc_info=True)
            await update.message.reply_text(f"❌ 목록 조회 실패: {str(e)[:200]}")
        return

    if len(args) < 2:
        await update.message.reply_text(
            "사용법: <code>/perf &lt;draft_id&gt; &lt;성과 메모&gt;</code>\n"
            "예: <code>/perf 42 좋아요 47개, 팔로워 +3. 훅 숫자 효과 좋음</code>\n"
            "인수 없이 <code>/perf</code> 만 입력하면 최근 메모 목록을 봅니다.",
            parse_mode="HTML",
        )
        return

    try:
        draft_id = int(args[0])
    except ValueError:
        await update.message.reply_text("❌ draft_id는 숫자여야 합니다.")
        return

    note_text = " ".join(args[1:])[:300]

    try:
        db = get_db()
        from app.services.draft_service import DraftService
        draft = DraftService(db).save_performance_note(draft_id, note_text)
        if not draft:
            await update.message.reply_text(f"❌ 초안 {draft_id}을 찾을 수 없습니다.")
            return
        await update.message.reply_text(
            f"📊 <b>성과 메모 저장됨</b> (draft #{draft_id})\n"
            f"<i>{note_text[:200]}</i>",
            parse_mode="HTML",
        )
        logger.info(f"[/perf] draft_id={draft_id} 성과 메모: {note_text[:60]}")
    except Exception as e:
        logger.error(f"/perf 오류: {e}", exc_info=True)
        await update.message.reply_text(f"❌ 성과 메모 저장 실패: {str(e)[:200]}")


async def note_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/note <draft_id> <메모> — 초안에 수동 메모 저장 (최대 500자)."""
    args = context.args or []
    if len(args) < 2:
        await update.message.reply_text(
            "사용법: <code>/note &lt;draft_id&gt; &lt;메모&gt;</code>\n"
            "예: <code>/note 42 각도를 경제 충격 쪽으로 바꿔줘</code>",
            parse_mode="HTML",
        )
        return

    try:
        draft_id = int(args[0])
    except ValueError:
        await update.message.reply_text("❌ draft_id는 숫자여야 합니다.")
        return

    note_text = " ".join(args[1:])[:500]

    try:
        db = get_db()
        from app.services.draft_service import DraftService
        draft_service = DraftService(db)
        draft = draft_service.get_by_id(draft_id)
        if not draft:
            await update.message.reply_text(f"❌ 초안 {draft_id}을 찾을 수 없습니다.")
            return

        draft.manual_notes = note_text
        db.commit()
        await update.message.reply_text(
            f"✅ <b>메모 저장됨</b> (draft #{draft_id})\n"
            f"<i>{note_text[:200]}</i>",
            parse_mode="HTML",
        )
        logger.info(f"[/note] draft_id={draft_id} 메모 저장: {note_text[:60]}")
    except Exception as e:
        logger.error(f"/note 오류: {e}", exc_info=True)
        await update.message.reply_text(f"❌ 메모 저장 실패: {str(e)[:200]}")


async def hint_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/hint <draft_id> <메모> — [HINT] prefix로 장기 힌트 저장 (다음 초안 반영용)."""
    args = context.args or []
    if len(args) < 2:
        await update.message.reply_text(
            "사용법: <code>/hint &lt;draft_id&gt; &lt;메모&gt;</code>\n"
            "예: <code>/hint 42 항상 통화정책 충격 각도로 써줘</code>\n"
            "<i>장기적으로 다음 초안 작성에 반영되는 힌트입니다.</i>",
            parse_mode="HTML",
        )
        return

    try:
        draft_id = int(args[0])
    except ValueError:
        await update.message.reply_text("❌ draft_id는 숫자여야 합니다.")
        return

    note_text = "[HINT] " + " ".join(args[1:])[:493]  # prefix 7자 포함 500자 이내

    try:
        db = get_db()
        from app.services.draft_service import DraftService
        draft_service = DraftService(db)
        draft = draft_service.get_by_id(draft_id)
        if not draft:
            await update.message.reply_text(f"❌ 초안 {draft_id}을 찾을 수 없습니다.")
            return

        draft.manual_notes = note_text
        db.commit()
        await update.message.reply_text(
            f"✅ <b>장기 힌트 저장됨</b> (draft #{draft_id})\n"
            f"<i>{note_text[:200]}</i>",
            parse_mode="HTML",
        )
        logger.info(f"[/hint] draft_id={draft_id} 힌트 저장: {note_text[:60]}")
    except Exception as e:
        logger.error(f"/hint 오류: {e}", exc_info=True)
        await update.message.reply_text(f"❌ 힌트 저장 실패: {str(e)[:200]}")


# =============================================================================
# 봇 앱 생성 & 실행
# =============================================================================

def create_telegram_app() -> Application | None:
    if not settings.has_telegram_config:
        logger.warning("텔레그램 설정 없음. 봇을 시작하지 않습니다.")
        return None

    app = Application.builder().token(settings.telegram_bot_token).build()

    # 커맨드
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("cancel", cancel_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("pending", pending_command))
    app.add_handler(CommandHandler("trends", trends_command))
    app.add_handler(CommandHandler("thread", thread_command))
    app.add_handler(CommandHandler("pack", pack_command))
    app.add_handler(CommandHandler("queue", queue_command))
    app.add_handler(CommandHandler("hunt", hunt_command))
    app.add_handler(CommandHandler("report", report_command))
    app.add_handler(CommandHandler("digest", digest_command))
    app.add_handler(CommandHandler("note", note_command))
    app.add_handler(CommandHandler("hint", hint_command))
    app.add_handler(CommandHandler("perf", perf_command))

    # 콜백 (모든 인라인 버튼)
    app.add_handler(CallbackQueryHandler(callback_handler))

    # 메시지: URL (http/https로 시작하는 텍스트)
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.Regex(r"^https?://"),
        url_message_handler,
    ))

    # 메시지: 일반 텍스트 (커뮤 복붙 등)
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & ~filters.Regex(r"^https?://"),
        text_message_handler,
    ))

    # 메시지: 사진
    app.add_handler(MessageHandler(filters.PHOTO, photo_message_handler))

    logger.info("텔레그램 봇 핸들러 등록 완료")
    return app


async def run_telegram_bot():
    app = create_telegram_app()
    if not app:
        logger.info("텔레그램 봇 비활성 (설정 없음)")
        return

    logger.info("텔레그램 봇 폴링 시작...")
    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)

    try:
        while True:
            await asyncio.sleep(1)
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("텔레그램 봇 종료 중...")
    finally:
        await app.updater.stop()
        await app.stop()
        await app.shutdown()
