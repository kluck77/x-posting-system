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
  6. Approve → 텍스트 복사 → 수동 게시

사용자 상태는 context.user_data에 저장합니다 (인메모리, 재시작 시 초기화).
"""

import asyncio
import json
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import (
    Application, CallbackQueryHandler, CommandHandler,
    MessageHandler, ContextTypes, filters,
)
from app.config import settings
from app.services.telegram_service import parse_callback_data, send_analysis_card
import re

from app.orchestrator import Orchestrator

logger = logging.getLogger(__name__)


# ─── 검증 결과 한국어 정규화 ──────────────────────────────────────────────────

def _normalize_to_korean(text: str) -> str:
    """영어 원문이 섞인 검증 결과를 한국어 bullet summary로 변환.
    완전한 번역은 아니고, 영어 문장이 주를 이루면 간단 정리.
    """
    if not text:
        return text

    # ASCII 비율로 영어 지배 여부 판단
    ascii_chars = sum(1 for c in text if ord(c) < 128 and c.isalpha())
    total_alpha = sum(1 for c in text if c.isalpha())
    if total_alpha == 0:
        return text

    eng_ratio = ascii_chars / total_alpha
    if eng_ratio < 0.5:
        # 한국어 위주면 그대로 반환
        return text

    # 영어가 50% 이상이면 → 간결한 한국어 대체
    # "The article states..." 등 전형적 패턴 정리
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    result_lines = []
    for line in lines:
        line_ascii = sum(1 for c in line if ord(c) < 128 and c.isalpha())
        line_alpha = sum(1 for c in line if c.isalpha())
        if line_alpha > 0 and (line_ascii / line_alpha) > 0.6:
            # 영어 문장 → 축약 표기
            result_lines.append(f"(영문 원문 — 로그 참조)")
            logger.info(f"[검증 원문] {line}")
            break  # 영어 원문은 하나만 표기
        else:
            result_lines.append(line)

    return "\n".join(result_lines) if result_lines else text

# ─── 메인 빠른 키보드 (입력창 위 고정) ─────────────────────────────────────────
MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [
        ["📝 초안", "📦 콘텐츠 팩", "📈 트렌드"],
        ["📊 현황", "📋 대기 큐", "🧵 스레드"],
        ["📰 다이제스트", "📊 주간", "💡 도움말"],
        ["💰 API 비용", "🔄 한도 초기화"],
    ],
    resize_keyboard=True,
    is_persistent=True,
)

# 버튼 텍스트 → 명령 매핑 (text_message_handler에서 디스패치)
_KEYBOARD_DISPATCH: dict[str, str] = {
    "📝 초안":       "draft",
    "📦 콘텐츠 팩":  "pack",
    "📈 트렌드":     "trends",
    "📊 현황":       "status",
    "📋 대기 큐":    "queue",
    "🧵 스레드":     "thread",
    "📰 다이제스트": "digest",
    "📊 주간":       "report",
    "💡 도움말":     "start",
    "💰 API 비용":    "cost",
    "🔄 한도 초기화": "reset_limit",
}

# 사용자 상태 키
STATE_KEY = "state"
PENDING_KEY = "pending"

# 상태값
STATE_IDLE = "idle"
STATE_AWAITING_TYPE = "awaiting_type"
STATE_AWAITING_REPLY_TARGET = "awaiting_reply_target"
STATE_AWAITING_THREAD_INPUT = "awaiting_thread_input"


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
    context.user_data.pop("_generating", None)


def _safe_error_msg(e: Exception) -> str:
    """에러 메시지에서 API 키를 마스킹하여 텔레그램 전송에 안전하게 만든다."""
    msg = str(e)[:200]
    for key in (settings.gemini_api_key, getattr(settings, "perplexity_api_key", ""),
                getattr(settings, "openai_api_key", ""), getattr(settings, "anthropic_api_key", "")):
        if key:
            msg = msg.replace(key, "***")
    return msg


async def _safe_remove_markup(query) -> None:
    """인라인 키보드 제거. 메시지 삭제/만료 시 조용히 무시."""
    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception:
        logger.debug("edit_message_reply_markup 실패 (무시)", exc_info=True)


def _parse_draft_id(args: list[str], pos: int = 0) -> tuple[int | None, str]:
    """
    args[pos]를 draft_id(int)로 파싱한다.

    Returns:
        (draft_id, "")         — 성공
        (None, error_message)  — 실패 (비어있거나 숫자 아님)
    """
    try:
        return int(args[pos]), ""
    except (ValueError, IndexError):
        return None, "❌ draft_id는 숫자여야 합니다."


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
    status_msg = await update.message.reply_text(
        "🔬 Gemini 리서치 + Perplexity 팩트체크 중..."
    )

    try:
        # Gemini & Perplexity 병렬 실행 (전체 timeout 적용)
        orchestrator = Orchestrator()
        try:
            research_task = orchestrator.ai.researcher.research(
                query=title, context=text[:1000]
            )
            factcheck_task = orchestrator.ai.fact_checker.check_facts(
                claim=text[:1000], context=title
            )
            research, factcheck = await asyncio.wait_for(
                asyncio.gather(
                    research_task, factcheck_task, return_exceptions=True
                ),
                timeout=_ANALYSIS_TIMEOUT,
            )
        finally:
            orchestrator.close()

        # 결과 정리
        research_summary = ""
        if isinstance(research, Exception):
            logger.error(f"[분석] Gemini 리서치 실패: {research}")
        else:
            facts = research.key_facts[:3]
            research_summary = _normalize_to_korean(research.summary[:300])
            if facts:
                kr_facts = [_normalize_to_korean(f) for f in facts]
                research_summary += "\n• " + "\n• ".join(kr_facts)

        factcheck_summary = ""
        if isinstance(factcheck, Exception):
            logger.error(f"[분석] Perplexity 팩트체크 실패: {factcheck}")
        else:
            status = "✅ 검증됨" if factcheck.verified else "⚠️ 미검증"
            confidence = factcheck.confidence
            factcheck_summary = f"{status} (신뢰도: {confidence})"
            if factcheck.corrections:
                # 영어 원문은 로그에만, 사용자에게는 한국어만 노출
                kr_corrections = [_normalize_to_korean(c) for c in factcheck.corrections[:2]]
                factcheck_summary += "\n수정사항:\n" + "\n".join(f"  • {c}" for c in kr_corrections)

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

    except asyncio.TimeoutError:
        logger.error(f"ANALYSIS_TIMEOUT: 분석 {_ANALYSIS_TIMEOUT}초 초과")
        await status_msg.edit_text(
            f"⏱ <b>분석 시간 초과</b> ({_ANALYSIS_TIMEOUT}초)\n\n다시 시도해주세요.",
            parse_mode="HTML",
        )
    except Exception as e:
        logger.error(f"분석 카드 생성 오류: {e}", exc_info=True)
        await status_msg.edit_text(f"❌ 분석 실패: {_safe_error_msg(e)}")


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

    # 밀도 체크 — 앱/랜딩/허브 페이지는 게시글 생성 차단
    if result.get("low_quality"):
        await status_msg.edit_text(
            "⚠️ <b>원문 링크가 아닌 것 같습니다</b>\n\n"
            f"📄 <b>{result['title'][:120]}</b>\n\n"
            "이 URL은 뉴스 기사가 아니라\n"
            "앱 랜딩 / 콘텐츠 허브 / 메뉴 페이지로 판단됩니다.\n"
            "(본문 밀도가 낮고 UI 요소가 많음)\n\n"
            "📋 <b>해결 방법:</b>\n"
            "① 기사 원문 URL을 직접 보내주세요\n"
            "② 또는 기사 본문 텍스트를 복사해서 붙여넣어 주세요",
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

    # ── 메인 키보드 버튼 디스패치 ──
    cmd_name = _KEYBOARD_DISPATCH.get(text)
    if cmd_name:
        handler_map = {
            "draft": draft_command,
            "pack": pack_command,
            "trends": trends_command,
            "status": status_command,
            "queue": queue_command,
            "thread": thread_command,
            "digest": digest_command,
            "report": report_command,
            "start": start_command,
            "cost": cost_command,
            "reset_limit": reset_limit_command,
        }
        handler = handler_map.get(cmd_name)
        if handler:
            # context.args 초기화 (인자 없는 호출)
            context.args = []
            await handler(update, context)
            return

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

_PIPELINE_TIMEOUT = 180   # 초안 생성 전체 hard timeout (초)
_PACK_TIMEOUT = 120       # 콘텐츠 팩 전체 hard timeout (초)
_ANALYSIS_TIMEOUT = 90    # 분석 카드 전체 hard timeout (초)


async def _run_pipeline(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    pending: dict,
    post_mode: str,               # "tweet" | "reply"
    reply_to_tweet_id: str | None = None,
):
    """
    pending 데이터를 이용해 AI 파이프라인을 실행하고 승인 카드를 전송합니다.
    전체 작업에 hard timeout을 걸어 무한 대기를 방지합니다.
    """
    # 중복 실행 방지
    if context.user_data.get("_generating"):
        await update.message.reply_text("⏳ 이미 생성 중입니다. 완료될 때까지 기다려주세요.")
        return
    context.user_data["_generating"] = True

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
        draft = await asyncio.wait_for(
            orchestrator.ingest_and_generate(source_data),
            timeout=_PIPELINE_TIMEOUT,
        )

        # 댓글 모드: reply_to_tweet_id 저장
        if post_mode == "reply" and reply_to_tweet_id:
            draft.reply_to_tweet_id = reply_to_tweet_id
            orchestrator.db.commit()

        card_sent = await orchestrator.send_for_approval(
            draft.id, chat_id=update.message.chat_id,
            skip_telegram_limit=True,  # 수동 /post는 텔레그램 제한 우회
        )

        mode_label = "📝 새 게시글" if post_mode == "tweet" else f"💬 댓글 (→{reply_to_tweet_id})"
        card_status = (
            "텔레그램으로 승인 카드가 전송됐어요."
            if card_sent
            else "⚠️ 승인 카드 전송 실패 — 서버 로그를 확인하세요."
        )
        await update.message.reply_text(
            f"✅ <b>초안 생성 완료!</b>\n"
            f"모드: {mode_label}\n"
            f"초안 ID: {draft.id}\n\n"
            f"{card_status}",
            parse_mode="HTML",
        )
    except asyncio.TimeoutError:
        logger.error(f"PIPELINE_TIMEOUT: 초안 생성 {_PIPELINE_TIMEOUT}초 초과")
        await update.message.reply_text(
            f"⏱ <b>초안 생성 시간 초과</b> ({_PIPELINE_TIMEOUT}초)\n\n"
            "서버 응답이 느립니다. 다시 시도해주세요.",
            parse_mode="HTML",
        )
    except Exception as e:
        logger.error(f"파이프라인 오류: {e}", exc_info=True)
        await update.message.reply_text(f"❌ 오류: {_safe_error_msg(e)}")
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
    try:
        await query.answer()
    except Exception:
        logger.debug("query.answer() 실패 (무시)", exc_info=True)

    callback_data = query.data
    logger.info(f"콜백 수신: {callback_data}")

    # --- 게시 큐 승인 콜백 ---
    if callback_data.startswith("queue_"):
        await _handle_queue_callback(query, context)
        return

    # --- 재답글 초안 콜백 ---
    if callback_data.startswith("reply_"):
        await _handle_reply_callback(query, context)
        return

    # --- 뉴스 모니터 알림 콜백 ---
    if callback_data.startswith("news_"):
        await _handle_news_callback(query, context)
        return

    # --- 퀵 액션 버튼 콜백 ---
    if callback_data.startswith("quick_"):
        await _handle_quick_callback(query, context)
        return

    # --- 후보 카드 훅 선택 콜백 ---
    if callback_data.startswith("hook_select:"):
        await _handle_hook_select_callback(query, context)
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
        await _safe_remove_markup(query)
        await query.message.reply_text("⚠️ 잘못된 요청입니다.")
        return

    action, draft_id = parsed
    await _safe_remove_markup(query)
    await query.answer()  # 콜백 로딩 표시 해제

    orchestrator = Orchestrator()
    try:
        result = await orchestrator.handle_approval(
            draft_id, action, chat_id=query.message.chat_id,
        )

        if result.get("success"):
            if action == "approve":
                import html as _html
                hook = result.get("hook", "") or ""
                body = result.get("body", "") or ""
                post_text = f"{hook}\n\n{body}".strip() if (hook or body) else ""
                if post_text:
                    response_text = (
                        f"✅ <b>승인 완료</b>\n\n"
                        f"<b>📋 게시용 텍스트:</b>\n"
                        f"<code>{_html.escape(post_text)}</code>"
                    )
                else:
                    response_text = f"✅ {result.get('message', '승인 완료')}"
            else:
                response_text = f"✅ {result.get('message', '완료!')}"
        else:
            response_text = f"⚠️ {result.get('error', '오류 발생')}"

        try:
            await query.message.reply_text(response_text, parse_mode="HTML")
        except Exception:
            # HTML 파싱 실패 시 일반 텍스트로 재시도
            await query.message.reply_text(response_text.replace("<b>", "").replace("</b>", "").replace("<code>", "").replace("</code>", ""))

    except Exception as e:
        logger.error(f"콜백 처리 오류: {e}", exc_info=True)
        await query.message.reply_text(f"❌ 오류: {_safe_error_msg(e)}")
    finally:
        orchestrator.close()


async def _handle_quick_callback(query, context: ContextTypes.DEFAULT_TYPE):
    """
    퀵 액션 인라인 버튼 콜백 처리.
    기존 커맨드 핸들러를 재사용하기 위해 query.message를 update.message로 래핑합니다.
    callback_data: quick_draft / quick_queue / quick_status / quick_monitor / quick_recover
    """

    class _U:
        """callback query 메시지를 command handler에 전달하기 위한 최소 래퍼."""
        message = query.message

    u = _U()
    action = query.data

    if action == "quick_draft":
        await query.message.reply_text(
            "✍️ <b>초안 만들기</b>\n\n"
            "URL 또는 텍스트를 보내주세요:\n"
            "• 뉴스 링크를 그냥 붙여넣거나\n"
            "• <code>/draft 주제나 내용</code> 으로 즉시 생성",
            parse_mode="HTML",
        )
    elif action == "quick_queue":
        await queue_command(u, context)
    elif action == "quick_status":
        await status_command(u, context)
    elif action == "quick_monitor":
        # context.args가 None이면 monitor_command는 "status"로 기본 처리됨
        await monitor_command(u, context)
    elif action == "quick_recover":
        await recover_command(u, context)
    elif action == "quick_cost":
        await cost_command(u, context)
    elif action == "quick_reset_limit":
        await reset_limit_command(u, context)


async def _handle_queue_callback(query, context: ContextTypes.DEFAULT_TYPE):
    """
    게시 큐 승인 콜백 처리.
    callback_data 형식: queue_approve:{post_key}
    post_key = QueuedPost.added_at.isoformat()
    """
    from app.services.growth.post_queue import get_post_queue

    data = query.data  # "queue_approve:2026-04-05T12:34:56.789012+00:00"
    parts = data.split(":", 1)
    if len(parts) != 2 or parts[0] != "queue_approve":
        await _safe_remove_markup(query)
        await query.message.reply_text("⚠️ 잘못된 큐 요청입니다.")
        return

    post_key = parts[1]
    await _safe_remove_markup(query)

    queue = get_post_queue()
    try:
        post = await queue.approve_queued_post(post_key)
    except Exception as e:
        logger.error(f"큐 게시 실패: {e}", exc_info=True)
        await query.message.reply_text(f"❌ 게시 실패: {_safe_error_msg(e)}")
        return

    if post:
        await query.message.reply_text(
            f"✅ <b>승인 완료!</b>\n\n"
            f"📋 <b>게시용 텍스트:</b>\n"
            f"<code>{post.text[:300]}</code>\n\n"
            f"📋 큐 잔여: {queue.count_pending()}개\n"
            f"위 텍스트를 복사해서 X에 붙여넣기 해주세요.",
            parse_mode="HTML",
        )
    else:
        await query.message.reply_text(
            "⚠️ 해당 게시물을 찾을 수 없습니다.\n이미 게시됐거나 큐에서 제거됐을 수 있습니다."
        )


async def _handle_reply_callback(query, context: ContextTypes.DEFAULT_TYPE):
    """
    재답글 초안 콜백 처리.
    callback_data 형식:
      reply_use:{reply_id}  — 초안 텍스트 재전송 (X에서 복사 사용)
      reply_skip:{reply_id} — 건너뜀
    """
    from app.services.growth.reply_monitor import get_pending_draft

    data = query.data
    parts = data.split(":", 1)
    if len(parts) != 2:
        await _safe_remove_markup(query)
        return

    action, reply_id = parts[0], parts[1]
    await _safe_remove_markup(query)

    if action == "reply_skip":
        await query.message.reply_text("⏭ 건너뜀.")
        return

    if action == "reply_use":
        entry = get_pending_draft(reply_id)
        if not entry:
            await query.message.reply_text(
                "⚠️ 초안 정보가 만료됐습니다.\n"
                "시스템이 재시작됐거나 오래된 알림일 수 있습니다."
            )
            return
        draft_text, author_username = entry
        x_link = f"https://x.com/{author_username}/status/{reply_id}"
        await query.message.reply_text(
            f"✍️ <b>재답글 초안</b>\n\n"
            f"<code>{draft_text}</code>\n\n"
            f"X에서 직접 답글 달기: {x_link}",
            parse_mode="HTML",
        )
        return

    # 알 수 없는 액션
    await query.message.reply_text("⚠️ 알 수 없는 요청입니다.")


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
        await _safe_remove_markup(query)
        return

    action, article_hash = parts[0], parts[1]
    await _safe_remove_markup(query)

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

        # 기사 정보는 재생성(news_regen) 버튼 클릭을 위해 유지.
        # skip 시에만 제거 (line 612). 봇 재시작 시 자연 소멸.

        # 초안 텍스트 전달 (자동 게시 없음 — 사용자가 직접 X에 붙여넣기)
        draft_text = f"{draft.hook}\n\n{draft.body}"
        if draft.thread_continuation:
            draft_text += f"\n\n🧵 {draft.thread_continuation}"

        score_line = f"📊 품질: {score}/100"

        char_count = len(draft_text)
        char_line = f"글자 수: {char_count}"
        if char_count > 280:
            char_line += " ⚠️ X 한도 초과 — 편집 필요"

        meta_lines = f"📋 {draft.category.value} | {draft.risk_level.value.upper()} | {char_line}"

        # topic tags (optional)
        try:
            import json as _json
            _tags = getattr(draft, "topic_tags", None)
            if _tags:
                _tag_list = _json.loads(_tags)
                if _tag_list:
                    meta_lines += "\n🏷 " + " ".join(f"#{t.lstrip('#')}" for t in _tag_list[:5])
        except Exception:
            pass

        # ai rationale (optional)
        _rationale = getattr(draft, "ai_rationale", None)
        if _rationale:
            meta_lines += f"\n🤖 {_rationale}"

        reply = (
            f"📝 <b>초안 완성!</b> {score_line}\n"
            f"{'─' * 28}\n"
            f"{draft_text}\n"
            f"{'─' * 28}\n"
            f"{meta_lines}\n\n"
            f"위 텍스트를 복사해서 X에 붙여넣기 해주세요."
        )

        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("🔄 재생성", callback_data=f"news_regen:{article_hash}"),
        ]])

        # 재생성용으로 기사 정보 유지
        await query.message.reply_text(reply, parse_mode="HTML", reply_markup=keyboard)

    except Exception as e:
        logger.error(f"뉴스 초안 생성 오류: {e}", exc_info=True)
        await query.message.reply_text(f"❌ 초안 생성 실패: {_safe_error_msg(e)}")


async def _handle_type_callback(query, context: ContextTypes.DEFAULT_TYPE):
    """[게시글 / 댓글 / 취소] 버튼 처리."""
    data = query.data  # type_tweet:123 / type_reply:123 / type_cancel:123
    parts = data.split(":", 1)
    if len(parts) != 2:
        await _safe_remove_markup(query)
        return

    action, msg_id = parts[0], parts[1]

    # 버튼 제거
    await _safe_remove_markup(query)

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
        await _run_candidate_card(
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
        "🇰🇷 <b>@cheesesvav 콘텐츠 시스템</b>\n\n"
        "버튼을 누르거나 URL / 텍스트 / 사진을 보내세요.\n\n"
        "<b>── 자주 쓰는 기능 ──</b>\n"
        "/draft — 단일 초안\n"
        "/pack — 콘텐츠 팩\n"
        "/thread — 스레드\n"
        "/trends — 트렌드 탐색\n"
        "/hunt — 댓글 기회\n\n"
        "<b>── 확인 / 관리 ──</b>\n"
        "/queue — 게시 큐\n"
        "/status — 시스템 상태\n"
        "/pending — 대기 초안\n"
        "/monitor — 멘션 모니터\n"
        "/cost — AI API 사용량/비용 확인\n"
        "/reset_limit — 일일 한도 초기화\n\n"
        "<b>── 분석 ──</b>\n"
        "/digest — 모닝 다이제스트\n"
        "/report — 주간 리포트\n"
        "/biz — 비즈니스 요약\n\n"
        "<b>── 메모 ──</b>\n"
        "/note · /hint · /perf\n\n"
        "<b>── 비즈니스 ──</b>\n"
        "/premium · /brief · /b2b · /cta\n"
        "/newsletter · /lead · /email\n\n"
        "<i>각 명령어만 입력하면 사용법이 나옵니다.</i>",
        parse_mode="HTML",
        reply_markup=MAIN_KEYBOARD,
    )


async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/menu — 퀵 액션 인라인 버튼 메뉴."""
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✍️ 초안 요청",   callback_data="quick_draft")],
        [InlineKeyboardButton("📋 대기 큐",      callback_data="quick_queue")],
        [InlineKeyboardButton("📊 오늘 현황",    callback_data="quick_status")],
        [InlineKeyboardButton("👀 모니터 확인",  callback_data="quick_monitor")],
        [InlineKeyboardButton("🛟 복구 점검",    callback_data="quick_recover")],
        [InlineKeyboardButton("💰 API 비용",     callback_data="quick_cost")],
        [InlineKeyboardButton("🔄 한도 초기화",  callback_data="quick_reset_limit")],
    ])
    await update.message.reply_text(
        "⚡ <b>오퍼레이터 메뉴</b>\n무엇을 할까요?",
        reply_markup=keyboard,
        parse_mode="HTML",
    )


async def cost_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/cost — AI API 사용량 및 예상 비용 표시."""
    try:
        from app.services.api_cost_tracker import get_usage_summary
        text = get_usage_summary()
    except Exception as e:
        text = f"API 비용 추적 로드 실패: {e}"

    await update.message.reply_text(
        text,
        parse_mode="HTML",
        reply_markup=MAIN_KEYBOARD,
    )


async def reset_limit_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/reset_limit — 오늘 카운트 초기화: PENDING/REJECTED/FAILED 삭제."""
    try:
        from app.db import SessionLocal
        from app.services.rate_limiter import RateLimiter
        from app.models.content import Draft, ApprovalStatus

        db = SessionLocal()
        try:
            limiter = RateLimiter(db)
            before_count = limiter.get_today_draft_count()
            before_ai = limiter.get_today_ai_draft_count()
            before_tg = limiter.get_today_telegram_count()

            # APPROVED / PUBLISHED 만 보존, 나머지 전체 삭제
            _keep = {ApprovalStatus.APPROVED, ApprovalStatus.PUBLISHED}
            start = limiter._today_start()
            deleted = (
                db.query(Draft)
                .filter(
                    Draft.created_at >= start,
                    ~Draft.approval_status.in_(_keep),
                )
                .delete(synchronize_session="fetch")
            )
            db.commit()

            after_count = limiter.get_today_draft_count()
            after_ai = limiter.get_today_ai_draft_count()
            after_tg = limiter.get_today_telegram_count()

            await update.message.reply_text(
                f"✅ <b>Rate Limit 초기화 완료</b>\n\n"
                f"<b>Before:</b>\n"
                f"  초안: {before_count}/{limiter.max_drafts}\n"
                f"  AI: {before_ai}/{limiter.max_ai_drafts}\n"
                f"  텔레그램: {before_tg}/{limiter.max_telegram}\n\n"
                f"<b>After:</b>\n"
                f"  초안: {after_count}/{limiter.max_drafts}\n"
                f"  AI: {after_ai}/{limiter.max_ai_drafts}\n"
                f"  텔레그램: {after_tg}/{limiter.max_telegram}\n\n"
                f"🗑 삭제: {deleted}건 (APPROVED/PUBLISHED 보존)",
                parse_mode="HTML",
            )
        finally:
            db.close()
    except Exception as e:
        logger.error(f"reset_limit 실패: {e}")
        await update.message.reply_text(f"❌ 초기화 실패: {e}")


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/cancel — 현재 상태 초기화"""
    state = _get_state(context)
    if state == STATE_IDLE:
        await update.message.reply_text("취소할 작업이 없어요.")
    else:
        _clear(context)
        await update.message.reply_text("✅ 취소됐어요. 새 링크나 사진을 보내주세요.")


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/status — 시스템 상태 요약."""
    from zoneinfo import ZoneInfo
    KST = ZoneInfo("Asia/Seoul")

    ai_status = settings.ai_status_summary()
    ai_lines = "\n".join(f"  {k}: {v}" for k, v in ai_status.items())

    # 멘션 모니터 상태 (Layer 2)
    try:
        from app.services.growth.monitor_state import is_paused
        monitor_label = "🔕 OFF (일시정지)" if is_paused() else "🔔 ON"
    except Exception:
        monitor_label = "?"

    # 게시 큐 대기 수 (Layer 2)
    try:
        from app.services.growth.post_queue import get_post_queue
        queue_count = get_post_queue().count_pending()
        queue_label = f"{queue_count}개 대기"
    except Exception:
        queue_label = "?"

    # 마지막 활동 시각 (Layer 2)
    try:
        from app.services.growth.activity_tracker import get_last_activity
        last = get_last_activity()
        activity_label = last.astimezone(KST).strftime("%m/%d %H:%M KST") if last else "없음"
    except Exception:
        activity_label = "?"

    approval_label = "수동 승인 ✅" if not settings.enable_auto_post_low_risk else "자동 게시 ⚠️"

    text = (
        "📊 <b>시스템 상태</b>\n\n"
        f"<b>AI 프로바이더</b>\n{ai_lines}\n\n"
        f"멘션 모니터: {monitor_label}\n"
        f"게시 큐: {queue_label}\n"
        f"마지막 활동: {activity_label}\n"
        f"승인 방식: {approval_label}"
    )
    await update.message.reply_text(text, parse_mode="HTML")


async def recover_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/recover — 영속 상태 파일 자가 진단."""
    from app.utils.startup_check import run_startup_check, format_recovery_summary
    results = run_startup_check()
    text = format_recovery_summary(results)
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
        text = "📋 <b>대기 초안</b>\n\n"
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
            text = f"📈 <b>현재 트렌드 ({topic})</b>\n\n"
            for i, t in enumerate(result["topics"][:10], 1):
                text += f"{i}. {t}\n"
            if result.get("notes"):
                text += f"\n💡 {result['notes'][:200]}"
            await update.message.reply_text(text, parse_mode="HTML")
        elif result.get("success"):
            await update.message.reply_text("📭 현재 감지된 트렌드가 없습니다.")
        else:
            await update.message.reply_text(f"⚠️ {result.get('error', '알 수 없는 오류')[:200]}")
    except Exception as e:
        await update.message.reply_text(f"❌ 오류: {_safe_error_msg(e)}")
    finally:
        orchestrator.close()


# =============================================================================
# /thread 커맨드 — 스레드 생성기
# =============================================================================


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
                    f"[Mock] 훅: {title[:80]}",
                    "[Mock] 핵심 팩트 — 구체적 숫자 포함.",
                    "[Mock] 해석 — 하나의 의견, 애매한 표현 없이.",
                    "[Mock] 한국 커뮤니티 반응은...",
                    "[Mock] 글로벌 영향 + 팔로우 유도.",
                ],
                content_pillar="economy",
                optimal_post_time="09:00 KST",
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
        await msg.edit_text(f"❌ 스레드 생성 실패: {_safe_error_msg(e)}")


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

    # 중복 실행 방지
    if context.user_data.get("_generating"):
        await update.message.reply_text("⏳ 이미 생성 중입니다. 완료될 때까지 기다려주세요.")
        return
    context.user_data["_generating"] = True

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
            # _run_analysis_and_show_card가 "text" 키로 저장하므로 동일하게 읽는다
            fetched_text = pending.get("text", "")
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

        # 팩 생성 (hard timeout)
        pack = await asyncio.wait_for(
            generate_content_pack(req),
            timeout=_PACK_TIMEOUT,
        )

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

    except asyncio.TimeoutError:
        logger.error(f"PACK_TIMEOUT: 콘텐츠 팩 생성 {_PACK_TIMEOUT}초 초과")
        await msg.edit_text(
            f"⏱ <b>콘텐츠 팩 생성 시간 초과</b> ({_PACK_TIMEOUT}초)\n\n다시 시도해주세요.",
            parse_mode="HTML",
        )
    except Exception as e:
        logger.error(f"콘텐츠 팩 생성 오류: {e}", exc_info=True)
        await msg.edit_text(f"❌ 콘텐츠 팩 생성 실패: {_safe_error_msg(e)}")
    finally:
        context.user_data.pop("_generating", None)


# =============================================================================
# 후보 카드 파이프라인 (2단계 구조)
# =============================================================================

CANDIDATE_CARD_KEY = "candidate_card"
CANDIDATE_SOURCE_KEY = "candidate_source"


async def _run_candidate_card(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    pending: dict | None = None,
    source_override: str | None = None,
) -> None:
    """후보 카드 생성 (1차 단계)."""
    from app.models.content_request import ContentRequest
    from app.services.content_pack import generate_candidate_card
    from app.services.telegram_service import send_candidate_card_messages
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    _clear(context)

    # 중복 실행 방지
    if context.user_data.get("_generating"):
        await update.message.reply_text("⏳ 이미 생성 중입니다. 완료될 때까지 기다려주세요.")
        return
    context.user_data["_generating"] = True

    msg = await update.message.reply_text("📋 <b>후보 카드 생성 중...</b>", parse_mode="HTML")

    try:
        # 입력 정규화
        source_text = ""
        if source_override:
            from app.services.content_fetcher import is_url
            if is_url(source_override):
                from app.services.content_fetcher import fetch_url_content
                fetched = await fetch_url_content(source_override)
                req = ContentRequest(
                    source_url=source_override,
                    source_type="news_link",
                    raw_text=fetched.get("text", ""),
                )
                source_text = fetched.get("text", "")
            else:
                req = ContentRequest(source_type="raw_text", raw_text=source_override)
                source_text = source_override
        elif pending:
            fetched_text = pending.get("text", "")
            req = ContentRequest(
                source_url=pending.get("url"),
                source_type="news_link" if pending.get("url") else "raw_text",
                raw_text=fetched_text,
            )
            source_text = fetched_text
        else:
            await msg.edit_text("⚠️ 소스 정보 없음. URL이나 텍스트를 보내주세요.")
            return

        if not req.has_content():
            await msg.edit_text("⚠️ 콘텐츠 내용이 부족합니다.")
            return

        # 검증 컨텍스트 조립 (상단 분석 결과 → 후보 카드에 전달)
        verification_context = ""
        if pending:
            parts = []
            fc = pending.get("factcheck_summary", "")
            if fc:
                parts.append(fc)
            rs = pending.get("research_summary", "")
            if rs:
                parts.append(f"리서치: {rs[:300]}")
            verification_context = "\n".join(parts)

        # 후보 카드 생성 (hard timeout)
        card = await asyncio.wait_for(
            generate_candidate_card(req, verification_context=verification_context),
            timeout=_PACK_TIMEOUT,
        )

        # user_data에 카드 + 소스 저장
        context.user_data[CANDIDATE_CARD_KEY] = card
        context.user_data[CANDIDATE_SOURCE_KEY] = source_text[:3000]

        await msg.delete()

        # 메시지 전송
        card_messages = send_candidate_card_messages(card)
        for cm in card_messages:
            text = cm["text"][:4096]
            hook_index = cm.get("hook_index")

            if hook_index is not None:
                keyboard = InlineKeyboardMarkup([[
                    InlineKeyboardButton(
                        "✏️ 이 훅으로 마감",
                        callback_data=f"hook_select:{hook_index}",
                    )
                ]])
                await update.message.reply_text(text, parse_mode="HTML", reply_markup=keyboard)
            else:
                await update.message.reply_text(text, parse_mode="HTML")

    except asyncio.TimeoutError:
        logger.error(f"CARD_TIMEOUT: 후보 카드 생성 {_PACK_TIMEOUT}초 초과")
        await msg.edit_text(
            f"⏱ <b>후보 카드 생성 시간 초과</b> ({_PACK_TIMEOUT}초)\n\n다시 시도해주세요.",
            parse_mode="HTML",
        )
    except Exception as e:
        logger.error(f"후보 카드 생성 오류: {e}", exc_info=True)
        await msg.edit_text(f"❌ 후보 카드 생성 실패: {_safe_error_msg(e)}")
    finally:
        context.user_data.pop("_generating", None)


async def _handle_hook_select_callback(
    query, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    hook_select:{index} 콜백 처리.
    선택된 훅으로 최종 마감 (2차 단계).
    """
    from app.services.content_pack import (
        generate_final_post, set_progress_callback, clear_progress_callback,
    )

    data = query.data  # hook_select:0
    parts = data.split(":", 1)
    if len(parts) != 2:
        return

    try:
        hook_index = int(parts[1])
    except ValueError:
        return

    card = context.user_data.get(CANDIDATE_CARD_KEY)
    if not card:
        await query.message.reply_text("⚠️ 후보 카드 세션 만료. /pack 으로 다시 시작해주세요.")
        return

    # 버튼 제거
    await _safe_remove_markup(query)

    msg = await query.message.reply_text("✏️ <b>최종 마감 중...</b>", parse_mode="HTML")

    # 단계별 진행 표시 콜백
    _stage_labels = {
        "openai": "✍️ OpenAI 초안 작성 중...",
        "grok_gemini": "🔍 Grok 평가 + Gemini 의견 수집 중...",
        "claude": "🧠 Claude 최종 편집 중...",
    }

    async def _on_progress(stage: str):
        label = _stage_labels.get(stage, f"⏳ {stage}...")
        try:
            await msg.edit_text(label, parse_mode="HTML")
        except Exception:
            pass

    set_progress_callback(_on_progress)

    try:
        source_text = context.user_data.get(CANDIDATE_SOURCE_KEY, "")
        result = await asyncio.wait_for(
            generate_final_post(card, hook_index, source_text),
            timeout=60,
        )

        clear_progress_callback()
        await msg.delete()

        # 최종 결과 전송
        selected_hook = card.hook_candidates[hook_index] if hook_index < len(card.hook_candidates) else "?"
        result_text = (
            f"✅ <b>최종 마감 완료</b>\n"
            f"📌 훅: {selected_hook}\n"
            f"{'─' * 28}\n\n"
            f"📝 <b>게시글</b> ({len(result.final_post)}자)\n"
            f"<code>{result.final_post}</code>\n\n"
        )
        if result.final_short:
            result_text += (
                f"⚡ <b>짧은 버전</b> ({len(result.final_short)}자)\n"
                f"<code>{result.final_short}</code>"
            )

        await query.message.reply_text(result_text, parse_mode="HTML")

    except asyncio.TimeoutError:
        clear_progress_callback()
        await msg.edit_text("⏱ <b>마감 시간 초과</b> (60초)\n\n다시 시도해주세요.", parse_mode="HTML")
    except Exception as e:
        clear_progress_callback()
        logger.error(f"최종 마감 오류: {e}", exc_info=True)
        await msg.edit_text(f"❌ 마감 실패: {_safe_error_msg(e)}")


async def _handle_pack_select_callback(
    query, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    pack_select:{index} 콜백 처리.
    선택된 포스트를 DB Draft로 저장하고 기존 승인 카드 전송.
    """
    parts = query.data.split(":", 1)
    if len(parts) != 2:
        await _safe_remove_markup(query)
        return

    try:
        pack_index = int(parts[1])
    except ValueError:
        await _safe_remove_markup(query)
        return

    await _safe_remove_markup(query)

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
            language="ko",
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
            f"⚠️ 승인 카드 생성 중 오류: {_safe_error_msg(e)}\n"
            "텍스트를 직접 복사해서 X에 게시할 수 있습니다.",
        )


async def pack_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/pack [url or text] — 후보 카드 생성 (2단계 구조 1차)."""
    args_text = " ".join(context.args).strip() if context.args else ""

    if args_text:
        await _run_candidate_card(update, context, source_override=args_text)
    else:
        await update.message.reply_text(
            "📋 <b>후보 카드 생성</b>\n\n"
            "사용법:\n"
            "• <code>/pack https://뉴스URL</code>\n"
            "• <code>/pack 한국은행 기준금리 2.75%로 동결. 수출 둔화 우려.</code>\n\n"
            "훅 후보에서 1개를 선택하면 최종 게시글이 생성됩니다.\n\n"
            "전체 팩(메인3+댓글3+인용2)이 필요하면: <code>/pack_full</code>",
            parse_mode="HTML",
        )


async def pack_full_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/pack_full [url or text] — 기존 전체 콘텐츠 팩 생성."""
    args_text = " ".join(context.args).strip() if context.args else ""

    if args_text:
        await _run_content_pack(update, context, source_override=args_text)
    else:
        await update.message.reply_text(
            "📦 <b>전체 콘텐츠 팩 생성</b>\n\n"
            "사용법:\n"
            "• <code>/pack_full https://뉴스URL</code>\n"
            "• <code>/pack_full 텍스트 입력</code>\n\n"
            "메인 3개 + 댓글 3개 + 인용 2개 + 짧은버전 1개를 한 번에 생성합니다.\n"
            "안전한 주제(제도/구조/해설)에 적합합니다.",
            parse_mode="HTML",
        )


async def draft_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/draft <url or text> — 분석 카드 없이 즉시 단일 초안 생성 (가장 빠른 경로).

    분석 카드를 거치지 않고 곧바로 AI 파이프라인(Gemini → OpenAI → Perplexity → Claude)을
    실행합니다. URL이면 콘텐츠를 먼저 수집합니다.

    사용법:
      /draft https://news.com/article
      /draft 한국은행 기준금리 2.75%로 동결 결정
    """
    args_text = " ".join(context.args).strip() if context.args else ""

    if not args_text:
        await update.message.reply_text(
            "📝 <b>즉시 초안 생성</b>\n\n"
            "사용법:\n"
            "• <code>/draft https://뉴스URL</code>\n"
            "• <code>/draft 기사 내용이나 메모</code>\n\n"
            "분석 카드 없이 바로 초안을 시작합니다.\n"
            "분석 후 의사결정이 필요하면 URL/텍스트를 그냥 보내주세요.",
            parse_mode="HTML",
        )
        return

    from app.services.content_fetcher import is_url, fetch_url_content

    msg = await update.message.reply_text("📝 초안 생성 중...")

    if is_url(args_text):
        result = await fetch_url_content(args_text)
        if result.get("source") == "failed" or not result.get("text"):
            await msg.edit_text(
                "⚠️ <b>URL 콘텐츠를 읽을 수 없습니다</b>\n\n"
                "텍스트를 직접 입력해주세요:\n"
                "<code>/draft 기사 본문 붙여넣기</code>",
                parse_mode="HTML",
            )
            return
        title = result.get("title") or args_text[:80]
        text = result["text"]
        source_url = args_text
        source_type = "manual"
    else:
        title = args_text[:80] + ("..." if len(args_text) > 80 else "")
        text = args_text
        source_url = None
        source_type = "community_input"

    await msg.delete()

    try:
        from app.services.growth.activity_tracker import record_activity
        record_activity()
    except Exception:
        pass

    pending = {
        "title": title,
        "text": text,
        "url": source_url,
        "source_type": source_type,
    }
    await _run_pipeline(update, context, pending=pending, post_mode="tweet")


# =============================================================================
# Growth 파이프라인 커맨드
# =============================================================================

async def monitor_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/monitor [off|on|status] — 멘션 모니터 제어."""
    from app.services.growth.monitor_state import is_paused, pause, resume

    sub = (context.args[0].lower() if context.args else "status")

    if sub == "off":
        if is_paused():
            await update.message.reply_text(
                "🔕 멘션 모니터가 이미 꺼져 있습니다.\n켜려면: /monitor on"
            )
        else:
            pause()
            await update.message.reply_text(
                "🔕 <b>멘션 모니터 OFF</b>\n\n"
                "새 답글 알림을 보내지 않습니다.\n"
                "켜려면: <code>/monitor on</code>",
                parse_mode="HTML",
            )

    elif sub == "on":
        if not is_paused():
            await update.message.reply_text(
                "🔔 멘션 모니터가 이미 켜져 있습니다."
            )
        else:
            resume()
            await update.message.reply_text(
                "🔔 <b>멘션 모니터 ON</b>\n\n"
                "새 답글이 있으면 5분 내에 알려드립니다.",
                parse_mode="HTML",
            )

    else:  # status or unknown subcommand
        state_label = "🔕 OFF (일시정지)" if is_paused() else "🔔 ON (활성)"
        await update.message.reply_text(
            f"📡 <b>멘션 모니터</b>: {state_label}\n\n"
            "<code>/monitor off</code> — 일시정지\n"
            "<code>/monitor on</code>  — 재개",
            parse_mode="HTML",
        )


async def queue_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/queue — 게시 큐 현황 조회 또는 항목 추가.

    /queue          → 큐 목록 표시
    /queue <본문>   → 큐에 추가
    """
    from app.services.growth.post_queue import get_post_queue

    args_text = " ".join(context.args).strip() if context.args else ""

    queue = get_post_queue()

    if args_text.lower().startswith("view "):
        # /queue view <n> — 대기 게시물 전체 텍스트 조회 (읽기 전용)
        rest = args_text[5:].strip()
        try:
            n = int(rest)
        except ValueError:
            await update.message.reply_text(
                "⚠️ <b>잘못된 번호입니다.</b>\n\n"
                "사용법: <code>/queue view 1</code>\n"
                "(번호는 /queue 목록에서 확인)",
                parse_mode="HTML",
            )
            return

        post = queue.get_pending_at(n)
        if post is None:
            pending_count = queue.count_pending()
            if pending_count == 0:
                await update.message.reply_text(
                    "📋 게시 큐가 비어 있습니다.\n"
                    "추가하려면: <code>/queue 게시할 본문 내용</code>",
                    parse_mode="HTML",
                )
            else:
                await update.message.reply_text(
                    f"⚠️ <b>{n}번 항목이 없습니다.</b>\n\n"
                    f"현재 대기 항목: {pending_count}개 (1–{pending_count})\n"
                    f"목록 확인: <code>/queue</code>",
                    parse_mode="HTML",
                )
            return

        from datetime import timedelta
        added_kst = (post.added_at + timedelta(hours=9)).strftime("%m/%d %H:%M KST")
        notified_line = "🔔 승인 알림 발송됨" if post.notified_at else "⏳ 알림 대기 중"
        char_info = f"{len(post.text)}자"
        if len(post.text) > 280:
            char_info += " ⚠️ X 한도 초과"
        await update.message.reply_text(
            f"📋 <b>큐 {n}번 항목</b>\n\n"
            f"<code>{post.text}</code>\n\n"
            f"📅 등록: {added_kst}\n"
            f"{notified_line}\n"
            f"✏️ {char_info}\n\n"
            f"<i>제거하려면: /queue remove {n}</i>",
            parse_mode="HTML",
        )
        return

    if args_text.lower().startswith("remove "):
        # /queue remove <n> — 대기 게시물 제거
        rest = args_text[7:].strip()
        try:
            n = int(rest)
        except ValueError:
            await update.message.reply_text(
                "⚠️ <b>잘못된 번호입니다.</b>\n\n"
                "사용법: <code>/queue remove 1</code>\n"
                "(번호는 /queue 목록에서 확인)",
                parse_mode="HTML",
            )
            return

        removed = queue.remove_pending(n)
        if removed is None:
            pending_count = queue.count_pending()
            if pending_count == 0:
                await update.message.reply_text(
                    "📋 큐가 비어 있습니다. 제거할 항목이 없습니다.",
                    parse_mode="HTML",
                )
            else:
                await update.message.reply_text(
                    f"⚠️ <b>{n}번 항목이 없습니다.</b>\n\n"
                    f"현재 대기 항목: {pending_count}개 (1–{pending_count})\n"
                    f"목록 확인: <code>/queue</code>",
                    parse_mode="HTML",
                )
            return

        preview = removed.text[:80] + ("…" if len(removed.text) > 80 else "")
        await update.message.reply_text(
            f"🗑 <b>{n}번 항목 제거 완료</b>\n\n"
            f"<code>{preview}</code>\n\n"
            f"📋 잔여 대기: {queue.count_pending()}개",
            parse_mode="HTML",
        )
        return

    if args_text.lower() in ("clear", "clear pending"):
        # /queue clear — 대기 항목 전체 제거
        removed = queue.clear_pending()
        if removed == 0:
            await update.message.reply_text("📋 큐가 이미 비어 있습니다.")
        else:
            await update.message.reply_text(
                f"🗑 <b>대기 항목 {removed}개 모두 제거됐습니다.</b>\n\n"
                "큐가 비어 있습니다.",
                parse_mode="HTML",
            )
        return

    if args_text:
        # 큐에 추가
        post = queue.add(args_text)
        pending_count = queue.count_pending()
        from datetime import datetime, timezone, timedelta
        added_kst = (post.added_at + timedelta(hours=9)).strftime("%H:%M KST")
        try:
            from app.services.growth.activity_tracker import record_activity
            record_activity()
        except Exception:
            pass
        await update.message.reply_text(
            f"✅ <b>큐에 추가됨</b>\n\n"
            f"<code>{post.text[:200]}</code>\n\n"
            f"📋 대기 중: {pending_count}개\n"
            f"🕐 등록 시각: {added_kst}\n\n"
            f"<i>최적 슬롯(9:00/10:30/12:00/13:30/15:00/19:00/21:00 KST)에 승인 알림이 발송됩니다.</i>",
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
        notified_mark = " 🔔" if p.notified_at else ""
        lines.append(
            f"{i}. [{added_kst}]{notified_mark} {p.text[:60]}{'…' if len(p.text) > 60 else ''}"
        )

    msg = (
        f"📋 <b>게시 큐 ({len(pending)}개 대기)</b>\n\n"
        + "\n".join(lines)
        + "\n\n<i>🔔 = 승인 알림 발송됨 · 순서대로 슬롯 알림.</i>"
        + "\n<i>상세 보기: /queue view &lt;번호&gt; · 제거: /queue remove &lt;번호&gt; · 전체 제거: /queue clear</i>"
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
        await msg.edit_text(f"❌ 탐색 실패: {_safe_error_msg(e)}")


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
        _db_perf = get_db()
        try:
            from app.services.draft_service import DraftService
            perf_section = DraftService(_db_perf).format_perf_summary(days=30)
            if perf_section:
                perf_section = f"\n\n{perf_section}"
        except Exception:
            pass
        finally:
            _db_perf.close()

        # Layer 2: 힌트 영향 요약 — [HINT]×[PERF] 공존 집계 (실패 시 무시)
        hint_impact = ""
        _db_hint = get_db()
        try:
            from app.services.draft_service import DraftService as _DS
            hint_impact = _DS(_db_hint).format_hint_impact_summary(days=60)
            if hint_impact:
                hint_impact = f"\n\n{hint_impact}"
        except Exception:
            pass
        finally:
            _db_hint.close()

        full_msg = (
            f"{report_text}{perf_section}{hint_impact}"
            f"\n\n<b>🤖 다음 주 개선 포인트</b>\n{ai_tips}"
        )

        await msg.delete()
        await update.message.reply_text(full_msg, parse_mode="HTML")

    except Exception as e:
        logger.error(f"/report 오류: {e}", exc_info=True)
        await msg.edit_text(f"❌ 리포트 생성 실패: {_safe_error_msg(e)}")


async def digest_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/digest — 모닝 다이제스트 즉시 생성."""
    from app.services.morning_digest import run_morning_digest

    msg = await update.message.reply_text("📰 <b>다이제스트 생성 중...</b>", parse_mode="HTML")

    try:
        await run_morning_digest()
        await msg.edit_text("✅ 다이제스트를 생성하여 전송했습니다.")
    except Exception as e:
        logger.error(f"/digest 오류: {e}", exc_info=True)
        await msg.edit_text(f"❌ 다이제스트 생성 실패: {_safe_error_msg(e)}")


async def perf_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/perf [draft_id] [메모] — 게시 후 성과 메모 추가. 인수 없으면 최근 목록 표시."""
    args = context.args or []

    if not args:
        # /perf 단독 → 최근 게시 + PERF 메모 목록
        db = get_db()
        try:
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
            await update.message.reply_text(f"❌ 목록 조회 실패: {_safe_error_msg(e)}")
        finally:
            db.close()
        return

    if len(args) < 2:
        await update.message.reply_text(
            "사용법: <code>/perf &lt;draft_id&gt; &lt;성과 메모&gt;</code>\n"
            "예: <code>/perf 42 좋아요 47개, 팔로워 +3. 훅 숫자 효과 좋음</code>\n"
            "인수 없이 <code>/perf</code> 만 입력하면 최근 메모 목록을 봅니다.",
            parse_mode="HTML",
        )
        return

    draft_id, err = _parse_draft_id(args, 0)
    if draft_id is None:
        await update.message.reply_text(err)
        return

    note_text = " ".join(args[1:])[:300]

    db = get_db()
    try:
        from app.services.draft_service import DraftService
        draft = DraftService(db).save_performance_note(draft_id, note_text)
        if not draft:
            await update.message.reply_text(f"❌ 초안 #{draft_id}을 찾을 수 없습니다.")
            return
        await update.message.reply_text(
            f"📊 <b>성과 메모 저장됨</b> (draft #{draft_id})\n"
            f"<i>{note_text[:200]}</i>",
            parse_mode="HTML",
        )
        logger.info(f"[/perf] draft_id={draft_id} 성과 메모: {note_text[:60]}")
    except Exception as e:
        logger.error(f"/perf 오류: {e}", exc_info=True)
        await update.message.reply_text(f"❌ 성과 메모 저장 실패: {_safe_error_msg(e)}")
    finally:
        db.close()


async def premium_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /premium — 프리미엄 Korea Brief 후보 관리.

    사용법:
      /premium              — 전체 요약
      /premium list [상태]  — 후보 목록 (상태 필터 가능)
      /premium view <id>    — 후보 상세 보기
      /premium status <id> <상태> — 상태 변경
      /premium note <id> <메모>   — 운영자 메모 저장
      /premium reader <id> <유형> — 대상 독자 설정
      /premium init         — 미초기화 후보 일괄 'new' 설정
      /premium export [상태] — 후보 내보내기 (텍스트)
    """
    args = context.args or []
    subcmd = args[0].lower() if args else "summary"

    db = get_db()
    try:
        from app.services.premium_candidate_service import PremiumCandidateService
        svc = PremiumCandidateService(db)

        # /premium (요약)
        if subcmd == "summary" or not args:
            text = svc.format_summary()
            await update.message.reply_text(text, parse_mode="HTML")

        # /premium list [상태]
        elif subcmd == "list":
            status_filter = args[1].lower() if len(args) > 1 else None
            candidates = svc.get_candidates(status=status_filter, limit=10)
            if not candidates:
                await update.message.reply_text(
                    f"⭐ 프리미엄 후보 없음" + (f" (상태: {status_filter})" if status_filter else "")
                )
                return
            lines = [f"⭐ <b>프리미엄 후보</b>" + (f" [{status_filter}]" if status_filter else "") + "\n"]
            for d in candidates:
                score = d.monetization_score or 0
                status = d.premium_status or "new"
                note_marker = " 📝" if d.premium_note else ""
                lines.append(
                    f"• ID {d.id} [{status}] 💰{score}{note_marker}\n"
                    f"  {(d.hook or '')[:50]}…"
                )
            await update.message.reply_text("\n".join(lines), parse_mode="HTML")

        # /premium view <id>
        elif subcmd == "view":
            if len(args) < 2:
                await update.message.reply_text("사용법: <code>/premium view &lt;id&gt;</code>", parse_mode="HTML")
                return
            draft_id, err = _parse_draft_id(args, 1)
            if draft_id is None:
                await update.message.reply_text(err)
                return
            draft = svc.get_candidate_by_id(draft_id)
            if not draft:
                await update.message.reply_text(f"❌ #{draft_id}는 프리미엄 후보가 아닙니다.")
                return
            text = svc.format_candidate_detail(draft)
            await update.message.reply_text(text, parse_mode="HTML")

        # /premium status <id> <상태>
        elif subcmd == "status":
            if len(args) < 3:
                from app.services.premium_candidate_service import PREMIUM_STATUSES
                statuses = " | ".join(PREMIUM_STATUSES)
                await update.message.reply_text(
                    f"사용법: <code>/premium status &lt;id&gt; &lt;상태&gt;</code>\n"
                    f"상태: {statuses}",
                    parse_mode="HTML",
                )
                return
            draft_id, err = _parse_draft_id(args, 1)
            if draft_id is None:
                await update.message.reply_text(err)
                return
            new_status = args[2].lower()
            result = svc.update_status(draft_id, new_status)
            if result:
                await update.message.reply_text(
                    f"✅ #{draft_id} 프리미엄 상태 → <b>{new_status}</b>",
                    parse_mode="HTML",
                )
            else:
                from app.services.premium_candidate_service import PREMIUM_STATUSES
                await update.message.reply_text(
                    f"❌ 상태 변경 실패. 유효한 상태: {', '.join(PREMIUM_STATUSES)}"
                )

        # /premium note <id> <메모>
        elif subcmd == "note":
            if len(args) < 3:
                await update.message.reply_text(
                    "사용법: <code>/premium note &lt;id&gt; &lt;메모&gt;</code>\n"
                    "예: <code>/premium note 42 expat 노동 이슈 브리프에 적합</code>",
                    parse_mode="HTML",
                )
                return
            draft_id, err = _parse_draft_id(args, 1)
            if draft_id is None:
                await update.message.reply_text(err)
                return
            note = " ".join(args[2:])[:500]
            result = svc.set_note(draft_id, note)
            if result:
                await update.message.reply_text(
                    f"📝 #{draft_id} 프리미엄 메모 저장:\n<i>{note[:200]}</i>",
                    parse_mode="HTML",
                )
            else:
                await update.message.reply_text(f"❌ #{draft_id}는 프리미엄 후보가 아닙니다.")

        # /premium reader <id> <유형>
        elif subcmd == "reader":
            if len(args) < 3:
                from app.services.premium_candidate_service import TARGET_READER_TYPES
                types = "\n".join(f"  • {t}" for t in TARGET_READER_TYPES)
                await update.message.reply_text(
                    f"사용법: <code>/premium reader &lt;id&gt; &lt;유형&gt;</code>\n\n"
                    f"추천 유형:\n{types}",
                    parse_mode="HTML",
                )
                return
            draft_id, err = _parse_draft_id(args, 1)
            if draft_id is None:
                await update.message.reply_text(err)
                return
            reader_type = args[2].lower()
            result = svc.set_target_reader(draft_id, reader_type)
            if result:
                await update.message.reply_text(
                    f"👤 #{draft_id} 대상 독자 → <b>{reader_type}</b>",
                    parse_mode="HTML",
                )
            else:
                await update.message.reply_text(f"❌ #{draft_id}는 프리미엄 후보가 아닙니다.")

        # /premium init
        elif subcmd == "init":
            count = svc.init_new_candidates()
            await update.message.reply_text(f"✅ {count}개 프리미엄 후보 'new' 상태 초기화됨")

        # /premium export [상태]
        elif subcmd == "export":
            status_filter = args[1].lower() if len(args) > 1 else None
            items = svc.export_candidates(status=status_filter, limit=10)
            if not items:
                await update.message.reply_text("⭐ 내보낼 프리미엄 후보 없음")
                return
            lines = [f"⭐ <b>프리미엄 후보 내보내기</b> ({len(items)}건)\n"]
            for item in items:
                lines.append(
                    f"──────────────\n"
                    f"ID: {item['draft_id']} | 💰{item['monetization_score'] or 0} | "
                    f"[{item['premium_status']}]\n"
                    f"훅: {item['hook'][:60]}…\n"
                    f"분류: {item['category']} | 위험도: {item['risk_level']}\n"
                    f"사유: {item['premium_reason'] or '—'}\n"
                    f"메모: {item['premium_note'] or '—'}\n"
                    f"독자: {item['target_reader_type'] or '—'}\n"
                    f"출처: {item['source_title'] or '—'}"
                )
            # 텔레그램 메시지 길이 제한 (4096자)
            text = "\n".join(lines)
            if len(text) > 4000:
                text = text[:4000] + "\n\n… (잘림)"
            await update.message.reply_text(text, parse_mode="HTML")

        else:
            await update.message.reply_text(
                "사용법:\n"
                "<code>/premium</code> — 요약\n"
                "<code>/premium list [상태]</code> — 목록\n"
                "<code>/premium view &lt;id&gt;</code> — 상세\n"
                "<code>/premium status &lt;id&gt; &lt;상태&gt;</code> — 상태 변경\n"
                "<code>/premium note &lt;id&gt; &lt;메모&gt;</code> — 메모\n"
                "<code>/premium reader &lt;id&gt; &lt;유형&gt;</code> — 독자 설정\n"
                "<code>/premium init</code> — 미초기화 후보 설정\n"
                "<code>/premium export [상태]</code> — 내보내기",
                parse_mode="HTML",
            )
    except Exception as e:
        logger.error(f"/premium 오류: {e}", exc_info=True)
        await update.message.reply_text(f"❌ 프리미엄 명령 실패: {_safe_error_msg(e)}")
    finally:
        db.close()


async def brief_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /brief — Premium Korea Brief 오퍼 준비 관리.

    사용법:
      /brief                          — 오퍼 현황 요약
      /brief view <id>                — 브리프 상세
      /brief status <id> <상태>       — 상태 변경
      /brief type <id> <유형>         — 브리프 유형 설정
      /brief reader <id> <독자>       — 대상 독자 설정
      /brief tier <id> <티어>         — 가격 티어 설정
      /brief note <id> <메모>         — 요약 메모 저장
      /brief export [상태]            — 내보내기
    """
    args = context.args or []
    subcmd = args[0].lower() if args else "summary"

    from app.db import get_db
    db = get_db()
    try:
        from app.services.brief_offer_service import BriefOfferService
        svc = BriefOfferService(db)

        # /brief (요약)
        if subcmd == "summary" or not args:
            text = svc.format_summary()
            await update.message.reply_text(text, parse_mode="HTML")

        # /brief view <id>
        elif subcmd == "view":
            if len(args) < 2:
                await update.message.reply_text(
                    "사용법: <code>/brief view &lt;id&gt;</code>", parse_mode="HTML"
                )
                return
            draft_id, err = _parse_draft_id(args, 1)
            if draft_id is None:
                await update.message.reply_text(err)
                return
            draft = svc.get_brief_by_id(draft_id)
            if not draft:
                await update.message.reply_text(f"❌ #{draft_id}는 프리미엄 후보가 아닙니다.")
                return
            text = svc.format_brief_detail(draft)
            await update.message.reply_text(text, parse_mode="HTML")

        # /brief status <id> <상태>
        elif subcmd == "status":
            if len(args) < 3:
                from app.services.brief_offer_service import BRIEF_STATUSES
                statuses = " | ".join(BRIEF_STATUSES)
                await update.message.reply_text(
                    f"사용법: <code>/brief status &lt;id&gt; &lt;상태&gt;</code>\n"
                    f"상태: {statuses}",
                    parse_mode="HTML",
                )
                return
            draft_id, err = _parse_draft_id(args, 1)
            if draft_id is None:
                await update.message.reply_text(err)
                return
            new_status = args[2].lower()
            result = svc.set_status(draft_id, new_status)
            if result:
                await update.message.reply_text(
                    f"📋 #{draft_id} Brief 상태 → <b>{new_status}</b>",
                    parse_mode="HTML",
                )
            else:
                from app.services.brief_offer_service import BRIEF_STATUSES
                await update.message.reply_text(
                    f"❌ 상태 변경 실패. 유효한 상태: {', '.join(BRIEF_STATUSES)}"
                )

        # /brief type <id> <유형>
        elif subcmd == "type":
            if len(args) < 3:
                from app.services.brief_offer_service import BRIEF_TYPES
                types = "\n".join(f"  • {t}" for t in BRIEF_TYPES)
                await update.message.reply_text(
                    f"사용법: <code>/brief type &lt;id&gt; &lt;유형&gt;</code>\n\n"
                    f"추천 유형:\n{types}",
                    parse_mode="HTML",
                )
                return
            draft_id, err = _parse_draft_id(args, 1)
            if draft_id is None:
                await update.message.reply_text(err)
                return
            brief_type = args[2].lower()
            result = svc.set_brief_type(draft_id, brief_type)
            if result:
                await update.message.reply_text(
                    f"📄 #{draft_id} Brief 유형 → <b>{brief_type}</b>",
                    parse_mode="HTML",
                )
            else:
                await update.message.reply_text(f"❌ #{draft_id}는 프리미엄 후보가 아닙니다.")

        # /brief reader <id> <독자>
        elif subcmd == "reader":
            if len(args) < 3:
                from app.services.brief_offer_service import BRIEF_TARGET_READERS
                readers = "\n".join(f"  • {r}" for r in BRIEF_TARGET_READERS)
                await update.message.reply_text(
                    f"사용법: <code>/brief reader &lt;id&gt; &lt;독자&gt;</code>\n\n"
                    f"추천 독자:\n{readers}",
                    parse_mode="HTML",
                )
                return
            draft_id, err = _parse_draft_id(args, 1)
            if draft_id is None:
                await update.message.reply_text(err)
                return
            reader = args[2].lower()
            result = svc.set_target_reader(draft_id, reader)
            if result:
                await update.message.reply_text(
                    f"👥 #{draft_id} Brief 대상 → <b>{reader}</b>",
                    parse_mode="HTML",
                )
            else:
                await update.message.reply_text(f"❌ #{draft_id}는 프리미엄 후보가 아닙니다.")

        # /brief tier <id> <티어>
        elif subcmd == "tier":
            if len(args) < 3:
                from app.services.brief_offer_service import BRIEF_PRICE_TIERS
                tiers = " | ".join(BRIEF_PRICE_TIERS)
                await update.message.reply_text(
                    f"사용법: <code>/brief tier &lt;id&gt; &lt;티어&gt;</code>\n"
                    f"티어: {tiers}",
                    parse_mode="HTML",
                )
                return
            draft_id, err = _parse_draft_id(args, 1)
            if draft_id is None:
                await update.message.reply_text(err)
                return
            tier = args[2].lower()
            result = svc.set_price_tier(draft_id, tier)
            if result:
                tier_labels = {"low": "💚 Low", "mid": "💛 Mid", "premium": "💎 Premium"}
                label = tier_labels.get(tier, tier)
                await update.message.reply_text(
                    f"💰 #{draft_id} Brief 티어 → <b>{label}</b>",
                    parse_mode="HTML",
                )
            else:
                from app.services.brief_offer_service import BRIEF_PRICE_TIERS
                await update.message.reply_text(
                    f"❌ 티어 변경 실패. 유효한 티어: {', '.join(BRIEF_PRICE_TIERS)}"
                )

        # /brief note <id> <메모>
        elif subcmd == "note":
            if len(args) < 3:
                await update.message.reply_text(
                    "사용법: <code>/brief note &lt;id&gt; &lt;메모&gt;</code>\n"
                    "예: <code>/brief note 42 Weekly Korea labor market brief for investors</code>",
                    parse_mode="HTML",
                )
                return
            draft_id, err = _parse_draft_id(args, 1)
            if draft_id is None:
                await update.message.reply_text(err)
                return
            note = " ".join(args[2:])[:500]
            result = svc.set_summary_note(draft_id, note)
            if result:
                await update.message.reply_text(
                    f"📝 #{draft_id} Brief 메모 저장:\n<i>{note[:200]}</i>",
                    parse_mode="HTML",
                )
            else:
                await update.message.reply_text(f"❌ #{draft_id}는 프리미엄 후보가 아닙니다.")

        # /brief export [상태]
        elif subcmd == "export":
            status_filter = args[1].lower() if len(args) > 1 else None
            items = svc.export_briefs(status=status_filter, limit=10)
            if not items:
                await update.message.reply_text("📋 내보낼 Brief 없음")
                return
            lines = [f"📋 <b>Brief 내보내기</b> ({len(items)}건)\n"]
            for item in items:
                tier = item.get("brief_price_tier") or "—"
                tier_labels = {"low": "💚", "mid": "💛", "premium": "💎"}
                tier_icon = tier_labels.get(tier, "")
                lines.append(
                    f"──────────────\n"
                    f"ID: {item['draft_id']} | 💰{item['monetization_score'] or 0} | "
                    f"[{item['premium_status']}]\n"
                    f"훅: {item['hook'][:60]}…\n"
                    f"유형: {item['brief_type'] or '—'} | "
                    f"티어: {tier_icon}{tier} | "
                    f"독자: {item['target_reader_type'] or '—'}\n"
                    f"메모: {item['brief_summary_note'] or '—'}"
                )
            text = "\n".join(lines)
            if len(text) > 4000:
                text = text[:4000] + "\n\n… (잘림)"
            await update.message.reply_text(text, parse_mode="HTML")

        else:
            await update.message.reply_text(
                "사용법:\n"
                "<code>/brief</code> — 요약\n"
                "<code>/brief view &lt;id&gt;</code> — 상세\n"
                "<code>/brief status &lt;id&gt; &lt;상태&gt;</code> — 상태 변경\n"
                "<code>/brief type &lt;id&gt; &lt;유형&gt;</code> — 브리프 유형\n"
                "<code>/brief reader &lt;id&gt; &lt;독자&gt;</code> — 대상 독자\n"
                "<code>/brief tier &lt;id&gt; &lt;티어&gt;</code> — 가격 티어\n"
                "<code>/brief note &lt;id&gt; &lt;메모&gt;</code> — 요약 메모\n"
                "<code>/brief export [상태]</code> — 내보내기",
                parse_mode="HTML",
            )
    except Exception as e:
        logger.error(f"/brief 오류: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Brief 명령 실패: {_safe_error_msg(e)}")
    finally:
        db.close()


async def cta_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /cta — CTA 유형 관리 + CTA 카피 라이브러리.
    /cta <id> <type>         — 드래프트 CTA 설정
    /cta list <type>         — CTA별 드래프트 목록
    /cta                     — CTA 분포 요약
    /cta copy                — CTA 카피 라이브러리 관리
    /cta perf                — CTA 카피 성과 요약
    /cta perf <id>           — 단일 카피 성과 상세
    /cta perf export         — 성과 내보내기
    /cta link <draft_id> <copy_id>  — 드래프트에 카피 연결
    /cta unlink <draft_id>          — 카피 연결 해제
    """
    args = context.args or []

    from app.db import get_db
    db = get_db()
    try:
        from app.services.email_lead_service import EmailLeadService, CTA_TYPES
        svc = EmailLeadService(db)

        subcmd = args[0].lower() if args else ""

        # /cta copy — CTA 카피 라이브러리 서브트리
        if subcmd == "copy":
            from app.services.cta_copy_service import CtaCopyService, CTA_COPY_TYPES
            csvc = CtaCopyService(db)
            copy_sub = args[1].lower() if len(args) > 1 else "summary"

            # /cta copy (요약)
            if copy_sub == "summary" or len(args) == 1:
                text = csvc.format_summary()
                await update.message.reply_text(text, parse_mode="HTML")

            # /cta copy add <type> <text>
            elif copy_sub == "add":
                if len(args) < 4:
                    types = " | ".join(CTA_COPY_TYPES)
                    await update.message.reply_text(
                        f"사용법: <code>/cta copy add &lt;type&gt; &lt;text&gt;</code>\n유형: {types}",
                        parse_mode="HTML",
                    )
                    return
                ct = args[2].lower()
                text = " ".join(args[3:])[:1000]
                result = csvc.add_copy(ct, text)
                if result:
                    await update.message.reply_text(
                        f"✅ CTA 카피 #{result.id} 추가 ({ct})\n"
                        f"<i>{text[:200]}</i>",
                        parse_mode="HTML",
                    )
                else:
                    await update.message.reply_text(
                        f"❌ 추가 실패. 유효 유형: {', '.join(CTA_COPY_TYPES)}"
                    )

            # /cta copy view <id>
            elif copy_sub == "view":
                if len(args) < 3:
                    await update.message.reply_text(
                        "사용법: <code>/cta copy view &lt;id&gt;</code>",
                        parse_mode="HTML",
                    )
                    return
                copy_id, err = _parse_draft_id(args, 2)
                if copy_id is None:
                    await update.message.reply_text(err)
                    return
                copy = csvc.get_by_id(copy_id)
                if not copy:
                    await update.message.reply_text(f"❌ 카피 #{copy_id} 없음")
                    return
                text = csvc.format_copy_detail(copy)
                await update.message.reply_text(text, parse_mode="HTML")

            # /cta copy edit <id> <text>
            elif copy_sub == "edit":
                if len(args) < 4:
                    await update.message.reply_text(
                        "사용법: <code>/cta copy edit &lt;id&gt; &lt;text&gt;</code>",
                        parse_mode="HTML",
                    )
                    return
                copy_id, err = _parse_draft_id(args, 2)
                if copy_id is None:
                    await update.message.reply_text(err)
                    return
                new_text = " ".join(args[3:])[:1000]
                result = csvc.edit_copy(copy_id, new_text)
                if result:
                    await update.message.reply_text(
                        f"✏️ 카피 #{copy_id} 수정 완료\n<i>{new_text[:200]}</i>",
                        parse_mode="HTML",
                    )
                else:
                    await update.message.reply_text(f"❌ 카피 #{copy_id} 수정 실패")

            # /cta copy note <id> <text>
            elif copy_sub == "note":
                if len(args) < 4:
                    await update.message.reply_text(
                        "사용법: <code>/cta copy note &lt;id&gt; &lt;text&gt;</code>",
                        parse_mode="HTML",
                    )
                    return
                copy_id, err = _parse_draft_id(args, 2)
                if copy_id is None:
                    await update.message.reply_text(err)
                    return
                note = " ".join(args[3:])[:500]
                result = csvc.set_note(copy_id, note)
                if result:
                    await update.message.reply_text(
                        f"📌 카피 #{copy_id} 메모 저장:\n<i>{note[:200]}</i>",
                        parse_mode="HTML",
                    )
                else:
                    await update.message.reply_text(f"❌ 카피 #{copy_id} 없음")

            # /cta copy on <id>
            elif copy_sub == "on":
                if len(args) < 3:
                    await update.message.reply_text(
                        "사용법: <code>/cta copy on &lt;id&gt;</code>",
                        parse_mode="HTML",
                    )
                    return
                copy_id, err = _parse_draft_id(args, 2)
                if copy_id is None:
                    await update.message.reply_text(err)
                    return
                result = csvc.activate(copy_id)
                if result:
                    await update.message.reply_text(f"✅ 카피 #{copy_id} 활성화")
                else:
                    await update.message.reply_text(f"❌ 카피 #{copy_id} 없음")

            # /cta copy off <id>
            elif copy_sub == "off":
                if len(args) < 3:
                    await update.message.reply_text(
                        "사용법: <code>/cta copy off &lt;id&gt;</code>",
                        parse_mode="HTML",
                    )
                    return
                copy_id, err = _parse_draft_id(args, 2)
                if copy_id is None:
                    await update.message.reply_text(err)
                    return
                result = csvc.deactivate(copy_id)
                if result:
                    await update.message.reply_text(f"⏸️ 카피 #{copy_id} 비활성화")
                else:
                    await update.message.reply_text(f"❌ 카피 #{copy_id} 없음")

            # /cta copy list [type]
            elif copy_sub == "list":
                ct_filter = args[2].lower() if len(args) > 2 else None
                if ct_filter:
                    copies = csvc.get_by_type(ct_filter, active_only=False)
                    label = ct_filter
                else:
                    copies = csvc.get_all()
                    label = "전체"
                if not copies:
                    await update.message.reply_text(f"📋 CTA 카피 없음 ({label})")
                    return
                lines = [f"📋 <b>CTA 카피</b> [{label}] ({len(copies)}건)\n"]
                for c in copies:
                    status = "✅" if c.is_active else "⏸️"
                    note_mark = " 📌" if c.note else ""
                    lines.append(
                        f"• #{c.id} [{c.cta_type}] {status}{note_mark}\n"
                        f"  {c.copy_text[:60]}…"
                    )
                await update.message.reply_text("\n".join(lines), parse_mode="HTML")

            # /cta copy export
            elif copy_sub == "export":
                items = csvc.export_copies()
                if not items:
                    await update.message.reply_text("📋 내보낼 CTA 카피 없음")
                    return
                lines = [f"📋 <b>CTA 카피 내보내기</b> ({len(items)}건)\n"]
                for item in items:
                    status = "✅" if item["is_active"] else "⏸️"
                    lines.append(
                        f"──────────────\n"
                        f"#{item['id']} [{item['cta_type']}] {status}\n"
                        f"Copy: {item['copy_text'][:80]}…\n"
                        f"메모: {item['note'] or '—'}"
                    )
                text = "\n".join(lines)
                if len(text) > 4000:
                    text = text[:4000] + "\n\n… (잘림)"
                await update.message.reply_text(text, parse_mode="HTML")

            else:
                types = " | ".join(CTA_COPY_TYPES)
                await update.message.reply_text(
                    "사용법:\n"
                    "<code>/cta copy</code> — 카피 라이브러리 요약\n"
                    "<code>/cta copy add &lt;type&gt; &lt;text&gt;</code> — 추가\n"
                    "<code>/cta copy view &lt;id&gt;</code> — 상세\n"
                    "<code>/cta copy edit &lt;id&gt; &lt;text&gt;</code> — 수정\n"
                    "<code>/cta copy note &lt;id&gt; &lt;text&gt;</code> — 메모\n"
                    "<code>/cta copy on &lt;id&gt;</code> — 활성화\n"
                    "<code>/cta copy off &lt;id&gt;</code> — 비활성화\n"
                    "<code>/cta copy list [type]</code> — 목록\n"
                    "<code>/cta copy export</code> — 내보내기\n\n"
                    f"유형: {types}",
                    parse_mode="HTML",
                )
            return

        # /cta perf — CTA 카피 성과 추적
        if subcmd == "perf":
            from app.services.cta_copy_service import CtaCopyService
            csvc = CtaCopyService(db)
            perf_sub = args[1].lower() if len(args) > 1 else "summary"

            # /cta perf (요약)
            if perf_sub == "summary" or len(args) == 1:
                text = csvc.format_perf_summary()
                await update.message.reply_text(text, parse_mode="HTML")

            # /cta perf export
            elif perf_sub == "export":
                items = csvc.export_perf()
                if not items:
                    await update.message.reply_text("📈 내보낼 성과 데이터 없음")
                    return
                lines = [f"📈 <b>CTA 카피 성과 내보내기</b> ({len(items)}건)\n"]
                for item in items:
                    status = "✅" if item["is_active"] else "⏸️"
                    pub_rate = (
                        f"{round(item['published'] / item['total_linked'] * 100)}%"
                        if item["total_linked"] > 0 else "—"
                    )
                    lines.append(
                        f"──────────────\n"
                        f"#{item['copy_id']} [{item['cta_type']}] {status}\n"
                        f"연결: {item['total_linked']} | 게시: {item['published']} ({pub_rate})\n"
                        f"평균 수익화: {item['avg_monetization']} | 고가치: {item['high_value_count']}\n"
                        f"Copy: {item['copy_text'][:60]}…"
                    )
                text = "\n".join(lines)
                if len(text) > 4000:
                    text = text[:4000] + "\n\n… (잘림)"
                await update.message.reply_text(text, parse_mode="HTML")

            # /cta perf <id>
            else:
                copy_id, err = _parse_draft_id(args, 1)
                if copy_id is None:
                    await update.message.reply_text(err)
                    return
                perf = csvc.get_copy_perf(copy_id)
                if not perf:
                    await update.message.reply_text(f"❌ 카피 #{copy_id} 성과 없음")
                    return
                text = csvc.format_perf_detail(perf)
                await update.message.reply_text(text, parse_mode="HTML")
            return

        # /cta link <draft_id> <copy_id>
        if subcmd == "link":
            if len(args) < 3:
                await update.message.reply_text(
                    "사용법: <code>/cta link &lt;draft_id&gt; &lt;copy_id&gt;</code>",
                    parse_mode="HTML",
                )
                return
            from app.services.cta_copy_service import CtaCopyService
            csvc = CtaCopyService(db)
            draft_id, err = _parse_draft_id(args, 1)
            if draft_id is None:
                await update.message.reply_text(err)
                return
            copy_id, err = _parse_draft_id(args, 2)
            if copy_id is None:
                await update.message.reply_text(err)
                return
            result = csvc.link_to_draft(draft_id, copy_id)
            if result:
                await update.message.reply_text(
                    f"🔗 드래프트 #{draft_id} → 카피 #{copy_id} 연결",
                    parse_mode="HTML",
                )
            else:
                await update.message.reply_text("❌ 연결 실패 (드래프트 또는 카피 없음)")
            return

        # /cta unlink <draft_id>
        if subcmd == "unlink":
            if len(args) < 2:
                await update.message.reply_text(
                    "사용법: <code>/cta unlink &lt;draft_id&gt;</code>",
                    parse_mode="HTML",
                )
                return
            from app.services.cta_copy_service import CtaCopyService
            csvc = CtaCopyService(db)
            draft_id, err = _parse_draft_id(args, 1)
            if draft_id is None:
                await update.message.reply_text(err)
                return
            result = csvc.unlink_from_draft(draft_id)
            if result:
                await update.message.reply_text(f"🔗 드래프트 #{draft_id} 카피 연결 해제")
            else:
                await update.message.reply_text(f"❌ 드래프트 #{draft_id} 없음")
            return

        # /cta (기존 기능: 분포 요약)
        if not args:
            by_cta = svc.group_by_cta()
            if not by_cta:
                await update.message.reply_text("📢 CTA 데이터 없음")
                return
            lines = ["📢 <b>CTA 분포</b>\n"]
            for cta, cnt in sorted(by_cta.items(), key=lambda x: -x[1]):
                lines.append(f"  • {cta}: {cnt}")
            lines.append(f"\n유효: {' | '.join(CTA_TYPES)}")
            await update.message.reply_text("\n".join(lines), parse_mode="HTML")

        # /cta list <type>
        elif subcmd == "list":
            if len(args) < 2:
                await update.message.reply_text(
                    f"사용법: <code>/cta list &lt;type&gt;</code>\n유효: {' | '.join(CTA_TYPES)}",
                    parse_mode="HTML",
                )
                return
            cta_type = args[1].lower()
            drafts = svc.get_by_cta(cta_type, limit=10)
            if not drafts:
                await update.message.reply_text(f"📢 CTA '{cta_type}' 항목 없음")
                return
            lines = [f"📢 <b>CTA: {cta_type}</b> ({len(drafts)}건)\n"]
            for d in drafts:
                lines.append(f"• ID {d.id} [{d.category.value if d.category else '—'}]\n  {(d.hook or '')[:50]}…")
            await update.message.reply_text("\n".join(lines), parse_mode="HTML")

        # /cta <id> <type> — 기존 CTA 설정
        else:
            draft_id, err = _parse_draft_id(args, 0)
            if draft_id is None:
                await update.message.reply_text(err)
                return
            if len(args) < 2:
                await update.message.reply_text(
                    f"사용법: <code>/cta &lt;id&gt; &lt;type&gt;</code>\n유효: {' | '.join(CTA_TYPES)}",
                    parse_mode="HTML",
                )
                return
            cta_type = args[1].lower()
            result = svc.set_cta(draft_id, cta_type)
            if result:
                await update.message.reply_text(
                    f"📢 #{draft_id} CTA → <b>{cta_type}</b>", parse_mode="HTML"
                )
            else:
                await update.message.reply_text(
                    f"❌ 실패. 유효한 CTA: {', '.join(CTA_TYPES)}"
                )
    except Exception as e:
        logger.error(f"/cta 오류: {e}", exc_info=True)
        await update.message.reply_text(f"❌ CTA 명령 실패: {_safe_error_msg(e)}")
    finally:
        db.close()


async def lead_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /lead — 리드 자산 관리.

    사용법:
      /lead                  — 리드자석 후보 목록
      /lead view <id>        — 상세
      /lead asset <id> <이름> — 리드 자산 이름 설정
      /lead type <id> <유형>  — 리드 자산 유형 설정
      /lead note <id> <메모>  — 리드 자산 메모
      /lead export            — 리드자석 후보 내보내기
    """
    args = context.args or []
    subcmd = args[0].lower() if args else "list"

    from app.db import get_db
    db = get_db()
    try:
        from app.services.email_lead_service import EmailLeadService, LEAD_ASSET_TYPES
        svc = EmailLeadService(db)

        # /lead (목록)
        if subcmd == "list" or not args:
            drafts = svc.get_lead_magnet_candidates(limit=10)
            if not drafts:
                await update.message.reply_text("📄 리드자석 후보 없음")
                return
            lines = [f"📄 <b>리드자석 후보</b> ({len(drafts)}건)\n"]
            for d in drafts:
                asset = d.lead_asset_name or "—"
                atype = d.lead_asset_type or "—"
                cta = d.cta_type or "—"
                lines.append(
                    f"• ID {d.id} [{cta}] 📄{atype}\n"
                    f"  {(d.hook or '')[:50]}…\n"
                    f"  └ {asset[:60]}"
                )
            await update.message.reply_text("\n".join(lines), parse_mode="HTML")

        # /lead view <id>
        elif subcmd == "view":
            if len(args) < 2:
                await update.message.reply_text(
                    "사용법: <code>/lead view &lt;id&gt;</code>", parse_mode="HTML"
                )
                return
            draft_id, err = _parse_draft_id(args, 1)
            if draft_id is None:
                await update.message.reply_text(err)
                return
            draft = svc._get_draft(draft_id)
            if not draft:
                await update.message.reply_text(f"❌ #{draft_id} 드래프트 없음")
                return
            text = svc.format_draft_detail(draft)
            await update.message.reply_text(text, parse_mode="HTML")

        # /lead asset <id> <이름>
        elif subcmd == "asset":
            if len(args) < 3:
                await update.message.reply_text(
                    "사용법: <code>/lead asset &lt;id&gt; &lt;이름&gt;</code>\n"
                    "예: <code>/lead asset 42 Korea Labor Law 2025 Checklist</code>",
                    parse_mode="HTML",
                )
                return
            draft_id, err = _parse_draft_id(args, 1)
            if draft_id is None:
                await update.message.reply_text(err)
                return
            name = " ".join(args[2:])[:200]
            result = svc.set_lead_asset(draft_id, name=name)
            if result:
                await update.message.reply_text(
                    f"📄 #{draft_id} 리드 자산 → <b>{name[:80]}</b>", parse_mode="HTML"
                )
            else:
                await update.message.reply_text(f"❌ #{draft_id} 드래프트 없음")

        # /lead type <id> <유형>
        elif subcmd == "type":
            if len(args) < 3:
                types = " | ".join(LEAD_ASSET_TYPES)
                await update.message.reply_text(
                    f"사용법: <code>/lead type &lt;id&gt; &lt;유형&gt;</code>\n유형: {types}",
                    parse_mode="HTML",
                )
                return
            draft_id, err = _parse_draft_id(args, 1)
            if draft_id is None:
                await update.message.reply_text(err)
                return
            asset_type = args[2].lower()
            result = svc.set_lead_asset(draft_id, asset_type=asset_type)
            if result:
                await update.message.reply_text(
                    f"📦 #{draft_id} 자산 유형 → <b>{asset_type}</b>", parse_mode="HTML"
                )
            else:
                await update.message.reply_text(
                    f"❌ 실패. 유효한 유형: {', '.join(LEAD_ASSET_TYPES)}"
                )

        # /lead note <id> <메모>
        elif subcmd == "note":
            if len(args) < 3:
                await update.message.reply_text(
                    "사용법: <code>/lead note &lt;id&gt; &lt;메모&gt;</code>",
                    parse_mode="HTML",
                )
                return
            draft_id, err = _parse_draft_id(args, 1)
            if draft_id is None:
                await update.message.reply_text(err)
                return
            note = " ".join(args[2:])[:500]
            result = svc.set_lead_asset(draft_id, note=note)
            if result:
                await update.message.reply_text(
                    f"📝 #{draft_id} 리드 메모 저장:\n<i>{note[:200]}</i>",
                    parse_mode="HTML",
                )
            else:
                await update.message.reply_text(f"❌ #{draft_id} 드래프트 없음")

        # /lead export
        elif subcmd == "export":
            from app.services.newsletter_routine_service import NewsletterRoutineService
            routine = NewsletterRoutineService(db)
            items = routine.export_lead_magnets(limit=10)
            if not items:
                await update.message.reply_text("📄 내보낼 리드자석 없음")
                return
            lines = [f"📄 <b>리드자석 내보내기</b> ({len(items)}건)\n"]
            for item in items:
                lines.append(
                    f"──────────────\n"
                    f"ID: {item['draft_id']} | CTA: {item['cta_type'] or '—'} | "
                    f"💰{item['monetization_score'] or 0}\n"
                    f"훅: {item['hook'][:60]}…\n"
                    f"Asset: {item['lead_asset_name'] or '—'} "
                    f"({item['lead_asset_type'] or '—'})\n"
                    f"메모: {item['lead_asset_note'] or '—'}"
                )
            text = "\n".join(lines)
            if len(text) > 4000:
                text = text[:4000] + "\n\n… (잘림)"
            await update.message.reply_text(text, parse_mode="HTML")

        else:
            await update.message.reply_text(
                "사용법:\n"
                "<code>/lead</code> — 리드자석 후보 목록\n"
                "<code>/lead view &lt;id&gt;</code> — 상세\n"
                "<code>/lead asset &lt;id&gt; &lt;이름&gt;</code> — 자산 이름\n"
                "<code>/lead type &lt;id&gt; &lt;유형&gt;</code> — 자산 유형\n"
                "<code>/lead note &lt;id&gt; &lt;메모&gt;</code> — 자산 메모\n"
                "<code>/lead export</code> — 내보내기",
                parse_mode="HTML",
            )
    except Exception as e:
        logger.error(f"/lead 오류: {e}", exc_info=True)
        await update.message.reply_text(f"❌ 리드 명령 실패: {_safe_error_msg(e)}")
    finally:
        db.close()


async def email_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /email — 이메일 버킷/목표 관리.

    사용법:
      /email                    — 요약
      /email bucket <id> <버킷> — 이메일 버킷 설정
      /email goal <id> <목표>   — 이메일 목표 설정
      /email list <버킷>        — 버킷별 목록
      /email newsletter         — 뉴스레터 후보 목록
      /email premium            — 프리미엄 티저 후보 목록
      /email export [cta] [bucket] — 내보내기
    """
    args = context.args or []
    subcmd = args[0].lower() if args else "summary"

    from app.db import get_db
    db = get_db()
    try:
        from app.services.email_lead_service import (
            EmailLeadService, EMAIL_BUCKETS, EMAIL_GOALS,
        )
        svc = EmailLeadService(db)

        # /email (요약)
        if subcmd == "summary" or not args:
            text = svc.format_summary()
            await update.message.reply_text(text, parse_mode="HTML")

        # /email bucket <id> <버킷>
        elif subcmd == "bucket":
            if len(args) < 3:
                buckets = " | ".join(EMAIL_BUCKETS)
                await update.message.reply_text(
                    f"사용법: <code>/email bucket &lt;id&gt; &lt;버킷&gt;</code>\n버킷: {buckets}",
                    parse_mode="HTML",
                )
                return
            draft_id, err = _parse_draft_id(args, 1)
            if draft_id is None:
                await update.message.reply_text(err)
                return
            bucket = args[2].lower()
            result = svc.set_email_bucket(draft_id, bucket)
            if result:
                await update.message.reply_text(
                    f"📬 #{draft_id} 이메일 버킷 → <b>{bucket}</b>", parse_mode="HTML"
                )
            else:
                await update.message.reply_text(
                    f"❌ 실패. 유효한 버킷: {', '.join(EMAIL_BUCKETS)}"
                )

        # /email goal <id> <목표>
        elif subcmd == "goal":
            if len(args) < 3:
                goals = " | ".join(EMAIL_GOALS)
                await update.message.reply_text(
                    f"사용법: <code>/email goal &lt;id&gt; &lt;목표&gt;</code>\n목표: {goals}",
                    parse_mode="HTML",
                )
                return
            draft_id, err = _parse_draft_id(args, 1)
            if draft_id is None:
                await update.message.reply_text(err)
                return
            goal = args[2].lower()
            result = svc.set_email_goal(draft_id, goal)
            if result:
                await update.message.reply_text(
                    f"🎯 #{draft_id} 이메일 목표 → <b>{goal}</b>", parse_mode="HTML"
                )
            else:
                await update.message.reply_text(
                    f"❌ 실패. 유효한 목표: {', '.join(EMAIL_GOALS)}"
                )

        # /email list <버킷>
        elif subcmd == "list":
            if len(args) < 2:
                buckets = " | ".join(EMAIL_BUCKETS)
                await update.message.reply_text(
                    f"사용법: <code>/email list &lt;버킷&gt;</code>\n버킷: {buckets}",
                    parse_mode="HTML",
                )
                return
            bucket = args[1].lower()
            drafts = svc.get_by_email_bucket(bucket, limit=10)
            if not drafts:
                await update.message.reply_text(f"📬 버킷 '{bucket}' 항목 없음")
                return
            lines = [f"📬 <b>이메일 버킷: {bucket}</b> ({len(drafts)}건)\n"]
            for d in drafts:
                goal = d.email_goal or "—"
                cta = d.cta_type or "—"
                lines.append(f"• ID {d.id} [CTA:{cta}] 🎯{goal}\n  {(d.hook or '')[:50]}…")
            await update.message.reply_text("\n".join(lines), parse_mode="HTML")

        # /email newsletter
        elif subcmd == "newsletter":
            drafts = svc.get_newsletter_candidates(limit=10)
            if not drafts:
                await update.message.reply_text("📧 뉴스레터 후보 없음")
                return
            lines = [f"📧 <b>뉴스레터 후보</b> ({len(drafts)}건)\n"]
            for d in drafts:
                cta = d.cta_type or "—"
                bucket = d.email_bucket or "—"
                lines.append(f"• ID {d.id} [CTA:{cta}] 📬{bucket}\n  {(d.hook or '')[:50]}…")
            await update.message.reply_text("\n".join(lines), parse_mode="HTML")

        # /email premium
        elif subcmd == "premium":
            drafts = svc.get_premium_teaser_candidates(limit=10)
            if not drafts:
                await update.message.reply_text("⭐ 프리미엄 티저 후보 없음")
                return
            lines = [f"⭐ <b>프리미엄 티저 후보</b> ({len(drafts)}건)\n"]
            for d in drafts:
                cta = d.cta_type or "—"
                bucket = d.email_bucket or "—"
                lines.append(f"• ID {d.id} [CTA:{cta}] 📬{bucket}\n  {(d.hook or '')[:50]}…")
            await update.message.reply_text("\n".join(lines), parse_mode="HTML")

        # /email export [cta=X] [bucket=X]
        elif subcmd == "export":
            cta_f = None
            bucket_f = None
            for a in args[1:]:
                if a.startswith("cta="):
                    cta_f = a[4:]
                elif a.startswith("bucket="):
                    bucket_f = a[7:]
            items = svc.export_email_items(cta_filter=cta_f, bucket_filter=bucket_f, limit=10)
            if not items:
                await update.message.reply_text("📧 내보낼 이메일/리드 항목 없음")
                return
            lines = [f"📧 <b>이메일/리드 내보내기</b> ({len(items)}건)\n"]
            for item in items:
                lines.append(
                    f"──────────────\n"
                    f"ID: {item['draft_id']} | CTA: {item['cta_type'] or '—'} | "
                    f"💰{item['monetization_score'] or 0}\n"
                    f"훅: {item['hook'][:60]}…\n"
                    f"Asset: {item['lead_asset_name'] or '—'} ({item['lead_asset_type'] or '—'})\n"
                    f"Bucket: {item['email_bucket'] or '—'} | Goal: {item['email_goal'] or '—'}"
                )
            text = "\n".join(lines)
            if len(text) > 4000:
                text = text[:4000] + "\n\n… (잘림)"
            await update.message.reply_text(text, parse_mode="HTML")

        else:
            await update.message.reply_text(
                "사용법:\n"
                "<code>/email</code> — 요약\n"
                "<code>/email bucket &lt;id&gt; &lt;버킷&gt;</code> — 버킷 설정\n"
                "<code>/email goal &lt;id&gt; &lt;목표&gt;</code> — 목표 설정\n"
                "<code>/email list &lt;버킷&gt;</code> — 버킷별 목록\n"
                "<code>/email newsletter</code> — 뉴스레터 후보\n"
                "<code>/email premium</code> — 프리미엄 티저 후보\n"
                "<code>/email export [cta=X] [bucket=X]</code> — 내보내기",
                parse_mode="HTML",
            )
    except Exception as e:
        logger.error(f"/email 오류: {e}", exc_info=True)
        await update.message.reply_text(f"❌ 이메일 명령 실패: {_safe_error_msg(e)}")
    finally:
        db.close()


async def weekly_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /weekly — 주간 운영 리포트.

    사용법:
      /weekly          — 주간 리포트 (7일)
      /weekly view     — 상세 리포트 (7일)
      /weekly export   — JSON 내보내기
      /weekly <N>      — 최근 N일 리포트
    """
    args = context.args or []
    subcmd = args[0].lower() if args else "summary"

    from app.db import get_db
    db = get_db()
    try:
        from app.services.weekly_report_service import WeeklyReportService
        svc = WeeklyReportService(db)

        # /weekly <N> — 숫자면 기간 지정
        days = 7
        if subcmd.isdigit():
            days = max(1, min(int(subcmd), 90))
            subcmd = "summary"

        # /weekly (간략 요약)
        if subcmd == "summary" or not args:
            report = svc.generate_report(days)
            text = svc.format_compact(report)
            await update.message.reply_text(text, parse_mode="HTML")

        # /weekly view [N]
        elif subcmd == "view":
            if len(args) > 1 and args[1].isdigit():
                days = max(1, min(int(args[1]), 90))
            report = svc.generate_report(days)
            text = svc.format_report(report)
            if len(text) > 4000:
                text = text[:4000] + "\n\n… (잘림)"
            await update.message.reply_text(text, parse_mode="HTML")

        # /weekly export [N]
        elif subcmd == "export":
            if len(args) > 1 and args[1].isdigit():
                days = max(1, min(int(args[1]), 90))
            report = svc.export_report(days)
            import json as _json
            text = _json.dumps(report, ensure_ascii=False, indent=2)
            if len(text) > 4000:
                text = text[:4000] + "\n\n… (잘림)"
            await update.message.reply_text(
                f"📊 <b>주간 리포트 (JSON)</b>\n\n<pre>{text}</pre>",
                parse_mode="HTML",
            )

        else:
            await update.message.reply_text(
                "사용법:\n"
                "<code>/weekly</code> — 간략 요약 (7일)\n"
                "<code>/weekly view</code> — 상세 리포트\n"
                "<code>/weekly export</code> — JSON 내보내기\n"
                "<code>/weekly &lt;N&gt;</code> — 최근 N일 요약\n"
                "<code>/weekly view &lt;N&gt;</code> — 최근 N일 상세",
                parse_mode="HTML",
            )
    except Exception as e:
        logger.error(f"/weekly 오류: {e}", exc_info=True)
        await update.message.reply_text(f"❌ 주간 리포트 실패: {_safe_error_msg(e)}")
    finally:
        db.close()


async def newsletter_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /newsletter — 뉴스레터/리드자석 운영 루틴.

    사용법:
      /newsletter                     — 운영 현황 요약
      /newsletter list [bucket]       — 후보 목록 (버킷별 필터)
      /newsletter view <id>           — 후보 상세
      /newsletter leads               — 리드자석 후보 목록
      /newsletter leads view <id>     — 리드자석 상세
      /newsletter export [bucket]     — 뉴스레터 후보 내보내기
      /newsletter leads export        — 리드자석 후보 내보내기
    """
    args = context.args or []
    subcmd = args[0].lower() if args else "summary"

    from app.db import get_db
    db = get_db()
    try:
        from app.services.newsletter_routine_service import (
            NewsletterRoutineService, NEWSLETTER_BUCKETS,
        )
        svc = NewsletterRoutineService(db)

        # /newsletter (요약)
        if subcmd == "summary" or not args:
            text = svc.format_newsletter_summary()
            await update.message.reply_text(text, parse_mode="HTML")

        # /newsletter list [bucket]
        elif subcmd == "list":
            bucket = args[1].lower() if len(args) > 1 else None
            if bucket:
                drafts = svc.get_by_bucket(bucket, limit=10)
                label = bucket
            else:
                drafts = svc.get_all_newsletter_candidates(limit=10)
                label = "전체"
            if not drafts:
                await update.message.reply_text(f"📰 뉴스레터 후보 없음 ({label})")
                return
            lines = [f"📰 <b>뉴스레터 후보</b> [{label}] ({len(drafts)}건)\n"]
            for d in drafts:
                bucket_v = d.email_bucket or "—"
                goal = d.email_goal or "—"
                cta = d.cta_type or "—"
                lines.append(
                    f"• ID {d.id} [{bucket_v}] CTA:{cta} 🎯{goal}\n"
                    f"  {(d.hook or '')[:50]}…"
                )
            await update.message.reply_text("\n".join(lines), parse_mode="HTML")

        # /newsletter view <id>
        elif subcmd == "view":
            if len(args) < 2:
                await update.message.reply_text(
                    "사용법: <code>/newsletter view &lt;id&gt;</code>",
                    parse_mode="HTML",
                )
                return
            draft_id, err = _parse_draft_id(args, 1)
            if draft_id is None:
                await update.message.reply_text(err)
                return
            draft = svc.get_draft_by_id(draft_id)
            if not draft:
                await update.message.reply_text(f"❌ #{draft_id} 드래프트 없음")
                return
            text = svc.format_newsletter_detail(draft)
            await update.message.reply_text(text, parse_mode="HTML")

        # /newsletter leads [view <id> | export]
        elif subcmd == "leads":
            lead_sub = args[1].lower() if len(args) > 1 else "list"

            if lead_sub == "view":
                if len(args) < 3:
                    await update.message.reply_text(
                        "사용법: <code>/newsletter leads view &lt;id&gt;</code>",
                        parse_mode="HTML",
                    )
                    return
                draft_id, err = _parse_draft_id(args, 2)
                if draft_id is None:
                    await update.message.reply_text(err)
                    return
                draft = svc.get_draft_by_id(draft_id)
                if not draft:
                    await update.message.reply_text(f"❌ #{draft_id} 드래프트 없음")
                    return
                text = svc.format_lead_detail(draft)
                await update.message.reply_text(text, parse_mode="HTML")

            elif lead_sub == "export":
                items = svc.export_lead_magnets(limit=10)
                if not items:
                    await update.message.reply_text("📄 내보낼 리드자석 없음")
                    return
                lines = [f"📄 <b>리드자석 내보내기</b> ({len(items)}건)\n"]
                for item in items:
                    lines.append(
                        f"──────────────\n"
                        f"ID: {item['draft_id']} | CTA: {item['cta_type'] or '—'} | "
                        f"💰{item['monetization_score'] or 0}\n"
                        f"훅: {item['hook'][:60]}…\n"
                        f"Asset: {item['lead_asset_name'] or '—'} "
                        f"({item['lead_asset_type'] or '—'})\n"
                        f"메모: {item['lead_asset_note'] or '—'}\n"
                        f"Bucket: {item['email_bucket'] or '—'} | "
                        f"Goal: {item['email_goal'] or '—'}"
                    )
                text = "\n".join(lines)
                if len(text) > 4000:
                    text = text[:4000] + "\n\n… (잘림)"
                await update.message.reply_text(text, parse_mode="HTML")

            else:
                # /newsletter leads (목록)
                drafts = svc.get_lead_magnet_candidates(limit=10)
                if not drafts:
                    await update.message.reply_text("📄 리드자석 후보 없음")
                    return
                lines = [f"📄 <b>리드자석 후보</b> ({len(drafts)}건)\n"]
                for d in drafts:
                    asset = d.lead_asset_name or "—"
                    atype = d.lead_asset_type or "—"
                    cta = d.cta_type or "—"
                    lines.append(
                        f"• ID {d.id} [{cta}] 📄{atype}\n"
                        f"  {(d.hook or '')[:50]}…\n"
                        f"  └ {asset[:60]}"
                    )
                await update.message.reply_text("\n".join(lines), parse_mode="HTML")

        # /newsletter export [bucket]
        elif subcmd == "export":
            bucket = args[1].lower() if len(args) > 1 else None
            items = svc.export_newsletter(bucket=bucket, limit=10)
            if not items:
                await update.message.reply_text("📰 내보낼 뉴스레터 후보 없음")
                return
            label = bucket or "전체"
            lines = [f"📰 <b>뉴스레터 내보내기</b> [{label}] ({len(items)}건)\n"]
            for item in items:
                lines.append(
                    f"──────────────\n"
                    f"ID: {item['draft_id']} | CTA: {item['cta_type'] or '—'} | "
                    f"💰{item['monetization_score'] or 0}\n"
                    f"훅: {item['hook'][:60]}…\n"
                    f"Bucket: {item['email_bucket'] or '—'} | "
                    f"Goal: {item['email_goal'] or '—'}\n"
                    f"Asset: {item['lead_asset_name'] or '—'}"
                )
            text = "\n".join(lines)
            if len(text) > 4000:
                text = text[:4000] + "\n\n… (잘림)"
            await update.message.reply_text(text, parse_mode="HTML")

        else:
            await update.message.reply_text(
                "사용법:\n"
                "<code>/newsletter</code> — 현황 요약\n"
                "<code>/newsletter list [bucket]</code> — 후보 목록\n"
                "<code>/newsletter view &lt;id&gt;</code> — 상세\n"
                "<code>/newsletter leads</code> — 리드자석 목록\n"
                "<code>/newsletter leads view &lt;id&gt;</code> — 리드자석 상세\n"
                "<code>/newsletter export [bucket]</code> — 내보내기\n"
                "<code>/newsletter leads export</code> — 리드자석 내보내기\n\n"
                f"버킷: {' | '.join(NEWSLETTER_BUCKETS)}",
                parse_mode="HTML",
            )
    except Exception as e:
        logger.error(f"/newsletter 오류: {e}", exc_info=True)
        await update.message.reply_text(f"❌ 뉴스레터 명령 실패: {_safe_error_msg(e)}")
    finally:
        db.close()


async def b2b_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /b2b — B2B 리서치 후보 관리.

    사용법:
      /b2b                          — 전체 요약
      /b2b list [상태]              — 후보 목록
      /b2b view <id>                — 후보 상세
      /b2b status <id> <상태>       — 상태 변경
      /b2b note <id> <메모>         — 운영자 메모
      /b2b audience <id> <대상>     — 대상 독자 설정
      /b2b usecase <id> <사례>      — 활용 사례 설정
      /b2b group [audience|usecase] [값] — 그룹핑/필터링
      /b2b report <id> [save|export]— 샘플 리포트 생성
      /b2b init                     — 미초기화 후보 일괄 'new'
      /b2b export [상태]            — 내보내기
    """
    args = context.args or []
    subcmd = args[0].lower() if args else "summary"

    from app.db import get_db
    db = get_db()
    try:
        from app.services.b2b_candidate_service import B2BCandidateService
        svc = B2BCandidateService(db)

        # /b2b (요약)
        if subcmd == "summary" or not args:
            text = svc.format_summary()
            await update.message.reply_text(text, parse_mode="HTML")

        # /b2b list [상태]
        elif subcmd == "list":
            status_filter = args[1].lower() if len(args) > 1 else None
            candidates = svc.get_candidates(status=status_filter, limit=10)
            if not candidates:
                await update.message.reply_text(
                    f"🏢 B2B 후보 없음" + (f" (상태: {status_filter})" if status_filter else "")
                )
                return
            lines = [f"🏢 <b>B2B 리서치 후보</b>" + (f" [{status_filter}]" if status_filter else "") + "\n"]
            for d in candidates:
                score = d.monetization_score or 0
                status = d.b2b_status or "new"
                aud = d.b2b_target_audience or "—"
                note_marker = " 📝" if d.b2b_note else ""
                lines.append(
                    f"• ID {d.id} [{status}] 💰{score} 👥{aud}{note_marker}\n"
                    f"  {(d.hook or '')[:50]}…"
                )
            await update.message.reply_text("\n".join(lines), parse_mode="HTML")

        # /b2b view <id>
        elif subcmd == "view":
            if len(args) < 2:
                await update.message.reply_text(
                    "사용법: <code>/b2b view &lt;id&gt;</code>", parse_mode="HTML"
                )
                return
            draft_id, err = _parse_draft_id(args, 1)
            if draft_id is None:
                await update.message.reply_text(err)
                return
            draft = svc.get_candidate_by_id(draft_id)
            if not draft:
                await update.message.reply_text(f"❌ #{draft_id}는 B2B 후보가 아닙니다.")
                return
            text = svc.format_candidate_detail(draft)
            await update.message.reply_text(text, parse_mode="HTML")

        # /b2b status <id> <상태>
        elif subcmd == "status":
            if len(args) < 3:
                from app.services.b2b_candidate_service import B2B_STATUSES
                statuses = " | ".join(B2B_STATUSES)
                await update.message.reply_text(
                    f"사용법: <code>/b2b status &lt;id&gt; &lt;상태&gt;</code>\n"
                    f"상태: {statuses}",
                    parse_mode="HTML",
                )
                return
            draft_id, err = _parse_draft_id(args, 1)
            if draft_id is None:
                await update.message.reply_text(err)
                return
            new_status = args[2].lower()
            result = svc.update_status(draft_id, new_status)
            if result:
                await update.message.reply_text(
                    f"🏢 #{draft_id} B2B 상태 → <b>{new_status}</b>",
                    parse_mode="HTML",
                )
            else:
                from app.services.b2b_candidate_service import B2B_STATUSES
                await update.message.reply_text(
                    f"❌ 상태 변경 실패. 유효한 상태: {', '.join(B2B_STATUSES)}"
                )

        # /b2b note <id> <메모>
        elif subcmd == "note":
            if len(args) < 3:
                await update.message.reply_text(
                    "사용법: <code>/b2b note &lt;id&gt; &lt;메모&gt;</code>\n"
                    "예: <code>/b2b note 42 규제 브리프로 investor 대상 적합</code>",
                    parse_mode="HTML",
                )
                return
            draft_id, err = _parse_draft_id(args, 1)
            if draft_id is None:
                await update.message.reply_text(err)
                return
            note = " ".join(args[2:])[:500]
            result = svc.set_note(draft_id, note)
            if result:
                await update.message.reply_text(
                    f"📝 #{draft_id} B2B 메모 저장:\n<i>{note[:200]}</i>",
                    parse_mode="HTML",
                )
            else:
                await update.message.reply_text(f"❌ #{draft_id}는 B2B 후보가 아닙니다.")

        # /b2b audience <id> <대상>
        elif subcmd == "audience":
            if len(args) < 3:
                from app.services.b2b_candidate_service import B2B_TARGET_AUDIENCES
                types = "\n".join(f"  • {t}" for t in B2B_TARGET_AUDIENCES)
                await update.message.reply_text(
                    f"사용법: <code>/b2b audience &lt;id&gt; &lt;대상&gt;</code>\n\n"
                    f"추천 대상:\n{types}",
                    parse_mode="HTML",
                )
                return
            draft_id, err = _parse_draft_id(args, 1)
            if draft_id is None:
                await update.message.reply_text(err)
                return
            audience = args[2].lower()
            result = svc.set_target_audience(draft_id, audience)
            if result:
                await update.message.reply_text(
                    f"👥 #{draft_id} B2B 대상 → <b>{audience}</b>",
                    parse_mode="HTML",
                )
            else:
                await update.message.reply_text(f"❌ #{draft_id}는 B2B 후보가 아닙니다.")

        # /b2b usecase <id> <사례>
        elif subcmd == "usecase":
            if len(args) < 3:
                from app.services.b2b_candidate_service import B2B_USE_CASES
                cases = "\n".join(f"  • {c}" for c in B2B_USE_CASES)
                await update.message.reply_text(
                    f"사용법: <code>/b2b usecase &lt;id&gt; &lt;사례&gt;</code>\n\n"
                    f"추천 사례:\n{cases}",
                    parse_mode="HTML",
                )
                return
            draft_id, err = _parse_draft_id(args, 1)
            if draft_id is None:
                await update.message.reply_text(err)
                return
            use_case = args[2].lower()
            result = svc.set_use_case(draft_id, use_case)
            if result:
                await update.message.reply_text(
                    f"📋 #{draft_id} B2B 활용 → <b>{use_case}</b>",
                    parse_mode="HTML",
                )
            else:
                await update.message.reply_text(f"❌ #{draft_id}는 B2B 후보가 아닙니다.")

        # /b2b group [audience|usecase] [값]
        elif subcmd == "group":
            group_type = args[1].lower() if len(args) > 1 else "overview"
            group_value = args[2].lower() if len(args) > 2 else None

            if group_type == "audience" and group_value:
                drafts = svc.get_by_audience(group_value, limit=10)
                if not drafts:
                    await update.message.reply_text(f"🏢 대상 '{group_value}' 후보 없음")
                    return
                lines = [f"🏢 <b>B2B 후보</b> — 👥 {group_value} ({len(drafts)}건)\n"]
                for d in drafts:
                    status = d.b2b_status or "new"
                    uc = d.b2b_use_case or "—"
                    lines.append(f"• ID {d.id} [{status}] 📋{uc}\n  {(d.hook or '')[:50]}…")
                await update.message.reply_text("\n".join(lines), parse_mode="HTML")

            elif group_type == "usecase" and group_value:
                drafts = svc.get_by_use_case(group_value, limit=10)
                if not drafts:
                    await update.message.reply_text(f"🏢 사례 '{group_value}' 후보 없음")
                    return
                lines = [f"🏢 <b>B2B 후보</b> — 📋 {group_value} ({len(drafts)}건)\n"]
                for d in drafts:
                    status = d.b2b_status or "new"
                    aud = d.b2b_target_audience or "—"
                    lines.append(f"• ID {d.id} [{status}] 👥{aud}\n  {(d.hook or '')[:50]}…")
                await update.message.reply_text("\n".join(lines), parse_mode="HTML")

            else:
                by_aud = svc.group_by_audience()
                by_uc = svc.group_by_use_case()
                lines = ["🏢 <b>B2B 그룹핑 현황</b>\n"]
                if by_aud:
                    lines.append("<b>대상 독자:</b>")
                    for aud, cnt in sorted(by_aud.items(), key=lambda x: -x[1]):
                        lines.append(f"  👥 {aud}: {cnt}건")
                    lines.append("")
                if by_uc:
                    lines.append("<b>활용 사례:</b>")
                    for uc, cnt in sorted(by_uc.items(), key=lambda x: -x[1]):
                        lines.append(f"  📋 {uc}: {cnt}건")
                if not by_aud and not by_uc:
                    lines.append("아직 audience/usecase가 설정된 후보 없음")
                lines.append("")
                lines.append(
                    "상세: <code>/b2b group audience investors</code>\n"
                    "상세: <code>/b2b group usecase regulation_brief</code>"
                )
                await update.message.reply_text("\n".join(lines), parse_mode="HTML")

        # /b2b report <id> [save|export]
        elif subcmd == "report":
            if len(args) < 2:
                await update.message.reply_text(
                    "사용법:\n"
                    "<code>/b2b report &lt;id&gt;</code> — 샘플 리포트 생성\n"
                    "<code>/b2b report &lt;id&gt; save</code> — 리포트 → 메모 저장\n"
                    "<code>/b2b report &lt;id&gt; export</code> — JSON 내보내기",
                    parse_mode="HTML",
                )
                return
            draft_id, err = _parse_draft_id(args, 1)
            if draft_id is None:
                await update.message.reply_text(err)
                return
            action = args[2].lower() if len(args) > 2 else "view"

            report = svc.generate_sample_report(draft_id)
            if not report:
                await update.message.reply_text(
                    f"❌ #{draft_id}는 B2B 후보가 아니거나 리포트 생성 실패"
                )
                return

            if action == "save":
                result = svc.save_report_to_note(draft_id, report)
                if result:
                    await update.message.reply_text(
                        f"💾 #{draft_id} 리포트 → b2b_note 저장 완료",
                        parse_mode="HTML",
                    )
                else:
                    await update.message.reply_text(f"❌ 리포트 저장 실패")
            elif action == "export":
                import json as _json
                text = _json.dumps(report, ensure_ascii=False, indent=2)
                if len(text) > 4000:
                    text = text[:4000] + "\n\n… (잘림)"
                await update.message.reply_text(
                    f"📄 <b>B2B 샘플 리포트 (JSON)</b>\n\n<pre>{text}</pre>",
                    parse_mode="HTML",
                )
            else:
                text = svc.format_sample_report(report)
                if len(text) > 4000:
                    text = text[:4000] + "\n\n… (잘림)"
                await update.message.reply_text(text, parse_mode="HTML")

        # /b2b init
        elif subcmd == "init":
            count = svc.init_new_candidates()
            await update.message.reply_text(f"✅ {count}개 B2B 후보 'new' 상태 초기화됨")

        # /b2b export [상태]
        elif subcmd == "export":
            status_filter = args[1].lower() if len(args) > 1 else None
            items = svc.export_candidates(status=status_filter, limit=10)
            if not items:
                await update.message.reply_text("🏢 내보낼 B2B 후보 없음")
                return
            lines = [f"🏢 <b>B2B 후보 내보내기</b> ({len(items)}건)\n"]
            for item in items:
                premium = ""
                if item.get("premium_linkage"):
                    premium = f"\n  ⭐ 프리미엄: {item['premium_linkage'].get('premium_status', '—')}"
                lines.append(
                    f"──────────────\n"
                    f"ID: {item['draft_id']} | 💰{item['monetization_score'] or 0} | "
                    f"[{item['b2b_status']}]\n"
                    f"훅: {item['hook'][:60]}…\n"
                    f"분류: {item['category']} | 위험도: {item['risk_level']}\n"
                    f"Audience: {item['b2b_target_audience'] or '—'}\n"
                    f"Use Case: {item['b2b_use_case'] or '—'}\n"
                    f"메모: {item['b2b_note'] or '—'}"
                    f"{premium}"
                )
            text = "\n".join(lines)
            if len(text) > 4000:
                text = text[:4000] + "\n\n… (잘림)"
            await update.message.reply_text(text, parse_mode="HTML")

        else:
            await update.message.reply_text(
                "사용법:\n"
                "<code>/b2b</code> — 요약\n"
                "<code>/b2b list [상태]</code> — 목록\n"
                "<code>/b2b view &lt;id&gt;</code> — 상세\n"
                "<code>/b2b status &lt;id&gt; &lt;상태&gt;</code> — 상태 변경\n"
                "<code>/b2b note &lt;id&gt; &lt;메모&gt;</code> — 메모\n"
                "<code>/b2b audience &lt;id&gt; &lt;대상&gt;</code> — 대상 독자\n"
                "<code>/b2b usecase &lt;id&gt; &lt;사례&gt;</code> — 활용 사례\n"
                "<code>/b2b group [audience|usecase] [값]</code> — 그룹핑\n"
                "<code>/b2b report &lt;id&gt; [save|export]</code> — 샘플 리포트\n"
                "<code>/b2b init</code> — 미초기화 후보 설정\n"
                "<code>/b2b export [상태]</code> — 내보내기",
                parse_mode="HTML",
            )
    except Exception as e:
        logger.error(f"/b2b 오류: {e}", exc_info=True)
        await update.message.reply_text(f"❌ B2B 명령 실패: {_safe_error_msg(e)}")
    finally:
        db.close()


async def biz_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /biz [summary|premium|b2b|newsletter] — 비즈니스 분류 요약/후보 조회.
    인수 없으면 7일 요약 표시.
    """
    args = context.args or []
    subcmd = args[0].lower() if args else "summary"

    db = get_db()
    try:
        from app.services.draft_service import DraftService
        svc = DraftService(db)

        if subcmd == "summary":
            text = svc.format_business_summary(days=7)
            await update.message.reply_text(text, parse_mode=None)

        elif subcmd == "premium":
            drafts = svc.get_premium_candidates(limit=5)
            if not drafts:
                await update.message.reply_text("⭐ 프리미엄 후보 없음")
                return
            lines = ["⭐ <b>프리미엄 브리프 후보</b>\n"]
            for d in drafts:
                score = d.monetization_score or 0
                reason = (d.premium_reason or "—")[:80]
                lines.append(
                    f"• ID {d.id} [{d.category.value}] 💰{score}\n"
                    f"  {(d.hook or '')[:50]}…\n"
                    f"  └ {reason}"
                )
            await update.message.reply_text("\n".join(lines), parse_mode="HTML")

        elif subcmd == "b2b":
            drafts = svc.get_b2b_candidates(limit=5)
            if not drafts:
                await update.message.reply_text("🏢 B2B 후보 없음")
                return
            lines = ["🏢 <b>B2B 리서치 후보</b>\n"]
            for d in drafts:
                aud = d.b2b_target_audience or "—"
                use = d.b2b_use_case or "—"
                lines.append(
                    f"• ID {d.id} [{d.category.value}] 🎯{aud}/{use}\n"
                    f"  {(d.hook or '')[:50]}…"
                )
            await update.message.reply_text("\n".join(lines), parse_mode="HTML")

        elif subcmd == "newsletter":
            drafts = svc.get_newsletter_candidates(limit=5)
            if not drafts:
                await update.message.reply_text("📧 뉴스레터 후보 없음")
                return
            lines = ["📧 <b>뉴스레터 후보</b>\n"]
            for d in drafts:
                cta = d.cta_type or "—"
                lines.append(
                    f"• ID {d.id} [{d.category.value}] 📢{cta}\n"
                    f"  {(d.hook or '')[:50]}…"
                )
            await update.message.reply_text("\n".join(lines), parse_mode="HTML")

        else:
            await update.message.reply_text(
                "사용법: <code>/biz [summary|premium|b2b|newsletter]</code>",
                parse_mode="HTML",
            )
    except Exception as e:
        logger.error(f"/biz 오류: {e}", exc_info=True)
        await update.message.reply_text(f"❌ 비즈니스 조회 실패: {_safe_error_msg(e)}")
    finally:
        db.close()


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

    draft_id, err = _parse_draft_id(args, 0)
    if draft_id is None:
        await update.message.reply_text(err)
        return

    note_text = " ".join(args[1:])[:500]

    db = get_db()
    try:
        from app.services.draft_service import DraftService
        draft_service = DraftService(db)
        draft = draft_service.get_by_id(draft_id)
        if not draft:
            await update.message.reply_text(f"❌ 초안 #{draft_id}을 찾을 수 없습니다.")
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
        db.rollback()
        logger.error(f"/note 오류: {e}", exc_info=True)
        await update.message.reply_text(f"❌ 메모 저장 실패: {_safe_error_msg(e)}")
    finally:
        db.close()


async def hint_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/hint <draft_id> <메모> | /hint clear <draft_id> — 장기 힌트 저장/제거."""
    args = context.args or []

    # /hint clear <draft_id>
    if args and args[0].lower() == "clear":
        if len(args) < 2:
            await update.message.reply_text(
                "사용법: <code>/hint clear &lt;draft_id&gt;</code>\n"
                "예: <code>/hint clear 42</code>",
                parse_mode="HTML",
            )
            return
        draft_id, err = _parse_draft_id(args, 1)
        if draft_id is None:
            await update.message.reply_text(err)
            return
        db = get_db()
        try:
            from app.services.draft_service import DraftService
            svc = DraftService(db)
            draft = svc.get_by_id(draft_id)
            if not draft:
                await update.message.reply_text(f"❌ 초안 #{draft_id}을 찾을 수 없습니다.")
                return
            had_hints = bool(draft.manual_notes and "[HINT]" in draft.manual_notes)
            svc.clear_hint_lines(draft_id)
            if had_hints:
                await update.message.reply_text(
                    f"✅ <b>힌트 제거됨</b> (draft #{draft_id})\n"
                    "<i>[HINT] 라인만 삭제됐습니다. 일반 메모·성과 메모는 유지됩니다.</i>",
                    parse_mode="HTML",
                )
            else:
                await update.message.reply_text(
                    f"ℹ️ draft #{draft_id}에 [HINT]가 없었습니다.",
                )
            logger.info(f"[/hint clear] draft_id={draft_id} had_hints={had_hints}")
        except Exception as e:
            logger.error(f"/hint clear 오류: {e}", exc_info=True)
            await update.message.reply_text(f"❌ 힌트 제거 실패: {_safe_error_msg(e)}")
        finally:
            db.close()
        return

    # /hint <draft_id> <메모>
    if len(args) < 2:
        await update.message.reply_text(
            "사용법:\n"
            "• <code>/hint &lt;draft_id&gt; &lt;메모&gt;</code> — 장기 힌트 저장\n"
            "• <code>/hint clear &lt;draft_id&gt;</code> — 힌트 제거\n"
            "예: <code>/hint 42 항상 통화정책 충격 각도로 써줘</code>",
            parse_mode="HTML",
        )
        return

    draft_id, err = _parse_draft_id(args, 0)
    if draft_id is None:
        await update.message.reply_text(err)
        return

    note_text = "[HINT] " + " ".join(args[1:])[:493]  # prefix 7자 포함 500자 이내

    db = get_db()
    try:
        from app.services.draft_service import DraftService
        draft_service = DraftService(db)
        draft = draft_service.get_by_id(draft_id)
        if not draft:
            await update.message.reply_text(f"❌ 초안 #{draft_id}을 찾을 수 없습니다.")
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
        db.rollback()
        logger.error(f"/hint 오류: {e}", exc_info=True)
        await update.message.reply_text(f"❌ 힌트 저장 실패: {_safe_error_msg(e)}")
    finally:
        db.close()


async def hints_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/hints — 현재 활성 [HINT] 목록 조회 (DraftWriter에 우선 반영될 힌트들)."""
    db = get_db()
    try:
        from app.services.draft_service import DraftService
        items = DraftService(db).get_hint_lines_with_draft_id(limit=10)
    except Exception as e:
        logger.error(f"/hints 조회 오류: {e}", exc_info=True)
        await update.message.reply_text(f"❌ 힌트 조회 실패: {_safe_error_msg(e)}")
        return
    finally:
        db.close()

    if not items:
        await update.message.reply_text(
            "활성 [HINT]가 없습니다.\n"
            "<code>/hint &lt;id&gt; &lt;메모&gt;</code> 로 장기 힌트를 추가하세요.",
            parse_mode="HTML",
        )
        return

    lines = ["📌 <b>활성 힌트 목록</b> (DraftWriter 우선 반영 대상)\n"]
    for draft_id, text in items:
        lines.append(f"• [#{draft_id}] {text}")
    lines.append(
        f"\n<i>총 {len(items)}개 — /hint &lt;id&gt; &lt;메모&gt; 로 추가</i>"
    )

    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


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
    app.add_handler(CommandHandler("menu", menu_command))
    app.add_handler(CommandHandler("cancel", cancel_command))
    app.add_handler(CommandHandler("cost", cost_command))
    app.add_handler(CommandHandler("reset_limit", reset_limit_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("recover", recover_command))
    app.add_handler(CommandHandler("pending", pending_command))
    app.add_handler(CommandHandler("trends", trends_command))
    app.add_handler(CommandHandler("draft", draft_command))
    app.add_handler(CommandHandler("thread", thread_command))
    app.add_handler(CommandHandler("pack", pack_command))
    app.add_handler(CommandHandler("pack_full", pack_full_command))
    app.add_handler(CommandHandler("queue", queue_command))
    app.add_handler(CommandHandler("monitor", monitor_command))
    app.add_handler(CommandHandler("hunt", hunt_command))
    app.add_handler(CommandHandler("report", report_command))
    app.add_handler(CommandHandler("digest", digest_command))
    app.add_handler(CommandHandler("note", note_command))
    app.add_handler(CommandHandler("hint", hint_command))
    app.add_handler(CommandHandler("hints", hints_command))
    app.add_handler(CommandHandler("perf", perf_command))
    app.add_handler(CommandHandler("biz", biz_command))
    app.add_handler(CommandHandler("premium", premium_command))
    app.add_handler(CommandHandler("brief", brief_command))
    app.add_handler(CommandHandler("b2b", b2b_command))
    app.add_handler(CommandHandler("weekly", weekly_command))
    app.add_handler(CommandHandler("cta", cta_command))
    app.add_handler(CommandHandler("lead", lead_command))
    app.add_handler(CommandHandler("email", email_command))
    app.add_handler(CommandHandler("newsletter", newsletter_command))

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
