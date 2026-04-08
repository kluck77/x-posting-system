"""
텔레그램 봇 핸들러
==================
텔레그램 인라인 버튼(Approve/Reject/Defer/Regenerate) 콜백을 처리합니다.

이 봇은 두 가지 모드로 실행할 수 있습니다:
1. 폴링 모드: 별도 서버 없이 직접 실행 (개발/개인 사용)
2. FastAPI와 함께: API 서버의 일부로 백그라운드 실행
"""

import asyncio
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CallbackQueryHandler, CommandHandler, ContextTypes,
)
from app.config import settings
from app.services.telegram_service import parse_callback_data
from app.orchestrator import Orchestrator

logger = logging.getLogger(__name__)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /start 명령어 처리.
    봇이 처음 시작될 때 안내 메시지를 보냅니다.
    """
    await update.message.reply_text(
        "🇰🇷 <b>X Posting System Bot</b>\n\n"
        "이 봇은 한국 이슈 영문 X 포스팅 시스템의 승인 봇입니다.\n\n"
        "📨 초안이 생성되면 이 채팅으로 승인 카드가 옵니다.\n"
        "✅ Approve = X에 게시\n"
        "❌ Reject = 거절\n"
        "⏸️ Defer = 나중에\n"
        "🔄 Regenerate = 다시 생성\n\n"
        "Commands:\n"
        "/status - 시스템 상태\n"
        "/pending - 대기 중인 초안\n",
        parse_mode="HTML",
    )


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/status 명령어 - 시스템 상태 표시"""
    ai_status = settings.ai_status_summary()
    status_lines = [f"  {name}: {status}" for name, status in ai_status.items()]
    text = (
        "📊 <b>System Status</b>\n\n"
        f"{'\\n'.join(status_lines)}\n\n"
        f"Auto-post: {'ON ⚠️' if settings.enable_auto_post_low_risk else 'OFF ✅'}"
    )
    await update.message.reply_text(text, parse_mode="HTML")


async def pending_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/pending 명령어 - 대기 중인 초안 목록"""
    from app.db import get_db
    from app.services.draft_service import DraftService

    db = get_db()
    try:
        service = DraftService(db)
        drafts = service.get_pending()

        if not drafts:
            await update.message.reply_text("📭 대기 중인 초안이 없습니다.")
            return

        text = "📋 <b>Pending Drafts</b>\n\n"
        for d in drafts[:10]:  # 최대 10개만
            text += (
                f"• ID {d.id}: {d.hook[:50]}...\n"
                f"  [{d.category.value}] [{d.risk_level.value}]\n\n"
            )

        await update.message.reply_text(text, parse_mode="HTML")
    finally:
        db.close()


async def _handle_hold_callback(query, action: str, item_id: int) -> None:
    """
    Hold 카드 버튼 콜백 처리 (옵션 A: 라우팅 + 안내 회신만).

    현재 세션 범위:
      - "잘못된 요청입니다" 차단
      - 버튼별 수신 확인 메시지 회신
      - DB 상태 변경 없음 (candidate 스키마 확정 전)

    다음 세션에서 promote/discard 실제 상태 변경을 별도로 구현한다.
    """
    logger.info(f"Hold 콜백 수신: action={action}, item_id={item_id}")

    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception as e:
        logger.warning(f"Hold 카드 키보드 제거 실패 (무시): {e}")

    if action == "hold_promote":
        text = (
            "📥 <b>Promote 요청 수신</b>\n\n"
            f"ID: {item_id}\n"
            "상태 변경 로직은 다음 세션에서 연결됩니다."
        )
    elif action == "hold_discard":
        text = (
            "🗑️ <b>Discard 요청 수신</b>\n\n"
            f"ID: {item_id}\n"
            "상태 변경 로직은 다음 세션에서 연결됩니다."
        )
    elif action == "hold_mark24":
        text = (
            "⏱️ <b>24h 표시 요청 수신</b>\n\n"
            f"ID: {item_id}\n"
            "스케줄러 미연결. 표시용 처리만 수행됩니다."
        )
    else:
        text = f"⚠️ 알 수 없는 hold action: {action}"

    try:
        await query.message.reply_text(text, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Hold 안내 메시지 전송 실패: {e}", exc_info=True)


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    인라인 버튼 콜백 처리.
    사용자가 Approve/Reject/Defer/Regenerate 버튼을 누르면 실행됩니다.
    """
    query = update.callback_query
    await query.answer()  # 텔레그램에 콜백 수신 확인

    callback_data = query.data
    logger.info(f"텔레그램 콜백 수신: {callback_data}")

    # callback_data 파싱: "action:draft_id"
    parsed = parse_callback_data(callback_data)
    if not parsed:
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text("⚠️ 잘못된 요청입니다.")
        return

    action, draft_id = parsed

    # Hold 카드 콜백은 전용 분기로 처리 (옵션 A: 라우팅 + 안내 회신만)
    # 실제 candidate 상태 변경은 스키마 확정 후 별도 세션에서 구현.
    if action.startswith("hold_"):
        await _handle_hold_callback(query, action, draft_id)
        return

    # 처리 중 표시
    action_labels = {
        "approve": "✅ Approving...",
        "reject": "❌ Rejecting...",
        "defer": "⏸️ Deferring...",
        "regenerate": "🔄 Regenerating...",
    }
    await query.edit_message_reply_markup(reply_markup=None)

    # 오케스트레이터로 처리
    orchestrator = Orchestrator()
    try:
        result = await orchestrator.handle_approval(draft_id, action)

        if result.get("success"):
            if action == "approve" and result.get("x_post_id"):
                response_text = (
                    f"✅ <b>APPROVED & POSTED</b>\n\n"
                    f"X Post ID: {result['x_post_id']}\n"
                    f"URL: {result.get('x_post_url', 'N/A')}"
                )
            else:
                response_text = f"✅ {result.get('message', 'Done!')}"
        else:
            response_text = f"⚠️ {result.get('error', 'Unknown error')}"

        await query.message.reply_text(response_text, parse_mode="HTML")

    except Exception as e:
        logger.error(f"콜백 처리 오류: {e}", exc_info=True)
        await query.message.reply_text(f"❌ 오류 발생: {str(e)[:200]}")
    finally:
        orchestrator.close()


def create_telegram_app() -> Application | None:
    """
    텔레그램 봇 Application을 생성합니다.
    텔레그램 설정이 없으면 None을 반환합니다.
    """
    if not settings.has_telegram_config:
        logger.warning("텔레그램 설정 없음. 봇을 시작하지 않습니다.")
        return None

    app = Application.builder().token(settings.telegram_bot_token).build()

    # 명령어 핸들러 등록
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("pending", pending_command))

    # 인라인 버튼 콜백 핸들러 등록
    app.add_handler(CallbackQueryHandler(callback_handler))

    logger.info("텔레그램 봇 핸들러 등록 완료")
    return app


async def run_telegram_bot():
    """
    텔레그램 봇을 폴링 모드로 실행합니다.
    이 함수는 별도 프로세스/스레드에서 실행됩니다.
    """
    app = create_telegram_app()
    if not app:
        logger.info("텔레그램 봇 비활성 (설정 없음)")
        return

    logger.info("텔레그램 봇 폴링 시작...")
    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)

    # 봇이 종료될 때까지 대기
    try:
        while True:
            await asyncio.sleep(1)
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("텔레그램 봇 종료 중...")
    finally:
        await app.updater.stop()
        await app.stop()
        await app.shutdown()
