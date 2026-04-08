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
# 서버 측 telegram_service 에는 hold 전용 파서 parse_hold_callback_data 가
# 별도로 존재할 수 있다 (서버/로컬 drift). 없으면 None 으로 두고
# callback_handler 에서 조건부 fallback 으로만 사용한다.
try:
    from app.services.telegram_service import (
        parse_hold_callback_data as _parse_hold_callback_data,
    )
except ImportError:
    _parse_hold_callback_data = None
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


def _do_hold_discard(source_id: int) -> str:
    """
    hold_discard 실 처리.
    source_items.candidate_status='rejected_manual' 후 사용자 회신 텍스트 반환.
    """
    from app.db import get_db
    from app.services.source_service import SourceService

    db = get_db()
    try:
        svc = SourceService(db)
        result = svc.mark_candidate_discarded(source_id)
    finally:
        db.close()

    if result == "ok":
        return (
            "🗑️ <b>Discard 처리 완료</b>\n\n"
            f"source_id: {source_id}\n"
            "candidate_status → rejected_manual"
        )
    if result == "not_found":
        return (
            "⚠️ <b>Discard 실패</b>\n\n"
            f"source_id={source_id} 를 찾을 수 없습니다."
        )
    if result == "schema_error":
        return (
            "⚠️ <b>Discard 실패 (스키마)</b>\n\n"
            "source_items.candidate_status 컬럼이 없습니다.\n"
            "서버 스키마 미배포 환경입니다."
        )
    return (
        "⚠️ <b>Discard 실패 (DB 오류)</b>\n\n"
        f"source_id={source_id}\n"
        "서버 로그를 확인하세요."
    )


async def _do_hold_promote(source_id: int) -> str:
    """
    hold_promote 실 처리.
    Orchestrator.promote_from_source 를 호출하고 결과 dict 를 사용자 회신
    텍스트로 매핑한다. full_pipeline 재진입 금지 (orchestrator 내부 메서드
    선택 위임).
    """
    orch = Orchestrator()
    try:
        try:
            result = await orch.promote_from_source(source_id)
        except Exception as e:
            logger.error(
                f"promote_from_source 호출 실패: source_id={source_id}, "
                f"err={e}",
                exc_info=True,
            )
            return (
                "❌ <b>Promote 실패 (호출 오류)</b>\n\n"
                f"source_id: {source_id}\n"
                f"서버 오류: {str(e)[:150]}"
            )
    finally:
        orch.close()

    reason = result.get("reason")

    # 성공 경로
    if result.get("success"):
        if reason == "ok":
            return (
                "✅ <b>Promote 완료</b>\n\n"
                f"source_id: {source_id}\n"
                f"draft_id: {result.get('draft_id')}\n"
                f"category: {result.get('category')}\n"
                f"risk: {result.get('risk_level')}\n"
                f"telegram_sent: {result.get('telegram_sent')}"
            )
        if reason == "draft_created_send_failed":
            return (
                "⚠️ <b>Promote 부분 성공</b>\n\n"
                f"source_id: {source_id}\n"
                f"draft_id: {result.get('draft_id')} 생성됨.\n"
                "승인 카드 전송 실패. 서버 로그 확인 필요.\n"
                f"error: {result.get('error', 'unknown')}"
            )

    # 실패 경로
    if reason == "not_found":
        return (
            "⚠️ <b>Promote 실패 — 원본 없음</b>\n\n"
            f"source_id={source_id} 를 찾을 수 없습니다."
        )
    if reason == "discarded":
        return (
            "⚠️ <b>Promote 실패 — 이미 discard</b>\n\n"
            f"source_id={source_id} 는 이미 discard 처리된 소스입니다.\n"
            "candidate_status=rejected_manual"
        )
    if reason == "already_promoted":
        existing_id = result.get("existing_draft_id")
        return (
            "⚠️ <b>Promote 실패 — 중복</b>\n\n"
            f"source_id={source_id} 에 이미 draft 가 존재합니다.\n"
            f"existing_draft_id: {existing_id}"
        )
    if reason == "rate_limit_draft":
        return (
            "⏳ <b>Promote 실패 — 초안 한도 초과</b>\n\n"
            f"{result.get('message', '오늘 초안 생성 한도 초과')}"
        )
    if reason == "rate_limit_telegram":
        return (
            "⏳ <b>Promote 실패 — 텔레그램 한도 초과</b>\n\n"
            f"{result.get('message', '오늘 텔레그램 전송 한도 초과')}"
        )
    if reason == "pipeline_error":
        return (
            "❌ <b>Promote 실패 — 파이프라인 오류</b>\n\n"
            f"source_id: {source_id}\n"
            f"error: {result.get('error', 'unknown')}"
        )
    return (
        "❌ <b>Promote 실패 — 알 수 없는 응답</b>\n\n"
        f"reason={reason}, success={result.get('success')}"
    )


def _do_hold_mark24_notice(source_id: int) -> str:
    """
    hold_mark24 안내 메시지 (DB 변경 없음).
    스케줄러 미연결 + candidate_status enum에 24h 전용 값이 확정되지 않아
    이번 세션에서는 표시 전용 처리만 수행한다.
    """
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    return (
        "⏱️ <b>24h 표시 (안내 전용)</b>\n\n"
        f"source_id: {source_id}\n"
        f"표시 시각: {now}\n"
        "스케줄러 미연결. 자동 삭제 없음. DB 변경 없음."
    )


async def _handle_hold_callback(query, action: str, item_id: int) -> None:
    """
    Hold 카드 버튼 콜백 처리.

    이번 세션 범위:
      - hold_discard:  source_items.candidate_status='rejected_manual' 실 처리
      - hold_mark24:   안내 + 타임스탬프만 (DB 변경 없음)
      - hold_promote:  orchestrator.promote_from_source 실 호출
                       (full_pipeline 재진입 금지, 기존 source_id 재사용)

    item_id 의미: source_items.id (서버 실측 확정)
    """
    logger.info(f"Hold 콜백 수신: action={action}, source_id={item_id}")

    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception as e:
        logger.warning(f"Hold 카드 키보드 제거 실패 (무시): {e}")

    if action == "hold_discard":
        text = _do_hold_discard(item_id)
    elif action == "hold_mark24":
        text = _do_hold_mark24_notice(item_id)
    elif action == "hold_promote":
        text = await _do_hold_promote(item_id)
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

    # === ACK 우선 + 실패 내성 ===
    # query.answer()는 "이 콜백 수신했음"을 텔레그램에 알리는 호출이다.
    # 늦거나 실패하면 클라이언트가 실패 팝업을 띄운다.
    # 네트워크/만료/타이밍으로 예외가 날 수 있으므로 try/except 로 감싸고,
    # 실패해도 본문(로그/파싱/라우팅/회신)은 계속 진행한다.
    try:
        await query.answer()
    except Exception as e:
        logger.warning(f"query.answer() 실패 (무시하고 진행): {e}")

    callback_data = query.data
    logger.info(f"텔레그램 콜백 수신: {callback_data}")

    # callback_data 파싱: "action:id"
    # 1차: 기본 파서 (approval + 로컬 확장 hold 포함)
    parsed = parse_callback_data(callback_data)
    # 2차 fallback: 서버 측 전용 파서 parse_hold_callback_data (있을 때만)
    # 서버는 hold_* 를 기본 파서에서 허용하지 않고 별도 함수로 처리하므로,
    # 1차가 None 일 때만 hold 전용 파서를 시도한다.
    if not parsed and _parse_hold_callback_data is not None:
        try:
            parsed = _parse_hold_callback_data(callback_data)
        except Exception as e:
            logger.warning(f"parse_hold_callback_data 호출 실패 (무시): {e}")
            parsed = None
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

    # concurrent_updates=True: ptb 기본은 직렬 처리라, approve 등 느린 콜백이
    # 진행 중이면 뒤이은 Hold/Approval 콜백이 큐에 밀려 query.answer()가
    # 늦어지고 텔레그램 클라이언트가 "실패 팝업"을 띄운다. 동시 처리로 전환해
    # 각 콜백이 독립 태스크에서 즉시 ACK 되도록 한다.
    app = (
        Application.builder()
        .token(settings.telegram_bot_token)
        .concurrent_updates(True)
        .build()
    )

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
