"""
ReplyMonitor 안정성 테스트
============================
post_reply() 예외 처리 및 rate limit 대응을 검증한다.
재답글 초안 인라인 버튼 동작을 검증한다.
"""

import pytest
import httpx
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch


class TestPostReplyErrorHandling:
    """post_reply() 예외/rate-limit 대응 테스트."""

    @pytest.mark.asyncio
    async def test_post_reply_returns_none_on_httpx_error(self):
        """httpx 네트워크 오류 시 None 반환 (예외 전파 없음)."""
        from app.services.growth.reply_monitor import ReplyMonitor
        monitor = ReplyMonitor()
        monitor._mock_mode = False  # mock 우회해서 실제 경로 테스트

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post.side_effect = httpx.ConnectError("연결 실패")
            mock_client_cls.return_value = mock_client

            result = await monitor.post_reply("tweet_123", "테스트 답글")

        assert result is None  # 예외 전파 없이 None 반환

    @pytest.mark.asyncio
    async def test_post_reply_returns_none_on_429(self):
        """X API 429 rate limit 시 None 반환."""
        from app.services.growth.reply_monitor import ReplyMonitor
        monitor = ReplyMonitor()
        monitor._mock_mode = False

        mock_response = MagicMock()
        mock_response.status_code = 429

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post.return_value = mock_response
            mock_client_cls.return_value = mock_client

            result = await monitor.post_reply("tweet_123", "테스트 답글")

        assert result is None

    @pytest.mark.asyncio
    async def test_post_reply_mock_mode_returns_id(self):
        """mock_mode=True이면 항상 성공하고 None이 아닌 ID 반환."""
        from app.services.growth.reply_monitor import ReplyMonitor
        monitor = ReplyMonitor()
        monitor._mock_mode = True
        result = await monitor.post_reply("tweet_123", "테스트 답글")
        assert result is not None
        assert "mock_reply_" in result


class TestFormatForTelegram:
    """format_for_telegram() HTML 형식 테스트."""

    def _make_reply(self):
        from app.services.growth.reply_monitor import IncomingReply
        return IncomingReply(
            reply_id="test_001",
            reply_text="좋은 질문이에요!",
            author_username="test_user",
            author_followers=500,
            parent_tweet_id="parent_001",
            parent_tweet_text="이것은 내 원문입니다.",
            created_at=datetime.now(timezone.utc) - timedelta(minutes=10),
            my_reply_draft="감사합니다! 더 자세히 설명드릴게요.",
        )

    def test_format_uses_html_bold(self):
        """HTML <b> 태그를 사용한다 (Markdown * 아님)."""
        reply = self._make_reply()
        msg = reply.format_for_telegram()
        assert "<b>새 답글 발견!</b>" in msg
        assert "*새 답글 발견!*" not in msg

    def test_format_uses_html_code(self):
        """텍스트를 <code> 태그로 감싼다 (백틱 아님)."""
        reply = self._make_reply()
        msg = reply.format_for_telegram()
        assert "<code>" in msg
        assert "`" not in msg

    def test_format_includes_author(self):
        """작성자 정보가 포함된다."""
        reply = self._make_reply()
        msg = reply.format_for_telegram()
        assert "@test_user" in msg
        assert "500" in msg

    def test_format_includes_draft(self):
        """재답글 초안이 포함된다."""
        reply = self._make_reply()
        msg = reply.format_for_telegram()
        assert "감사합니다! 더 자세히 설명드릴게요." in msg

    def test_format_includes_x_link(self):
        """X 링크가 포함된다."""
        reply = self._make_reply()
        msg = reply.format_for_telegram()
        assert "x.com/test_user/status/test_001" in msg


class TestPendingReplyDrafts:
    """store_pending_draft / get_pending_draft 테스트."""

    def test_store_and_get(self):
        """저장 후 조회 가능."""
        from app.services.growth.reply_monitor import store_pending_draft, get_pending_draft
        store_pending_draft("reply_abc", "초안 텍스트", "user123")
        result = get_pending_draft("reply_abc")
        assert result is not None
        draft, username = result
        assert draft == "초안 텍스트"
        assert username == "user123"

    def test_get_missing_returns_none(self):
        """없는 reply_id 조회 시 None 반환."""
        from app.services.growth.reply_monitor import get_pending_draft
        assert get_pending_draft("nonexistent_id_xyz_9999") is None

    def test_overflow_removes_oldest(self):
        """100개 초과 시 가장 오래된 항목이 제거된다."""
        from app.services.growth.reply_monitor import (
            store_pending_draft, get_pending_draft, _pending_reply_drafts
        )
        _pending_reply_drafts.clear()

        for i in range(100):
            store_pending_draft(f"reply_{i:04d}", f"draft {i}", "user")

        # 101번째 추가 → reply_0000 제거
        store_pending_draft("reply_overflow", "new draft", "user")
        assert get_pending_draft("reply_0000") is None
        assert get_pending_draft("reply_overflow") is not None


class TestRunReplyMonitorInlineButton:
    """run_reply_monitor()가 인라인 버튼과 함께 전송하는지 검증."""

    @pytest.mark.asyncio
    async def test_sends_with_keyboard_not_plain_text(self):
        """tg_send_with_keyboard가 호출되고 tg_send는 호출되지 않는다."""
        from app.services.growth import reply_monitor as rm

        mock_reply = MagicMock()
        mock_reply.reply_id = "test_reply_btn"
        mock_reply.author_username = "btn_user"
        mock_reply.my_reply_draft = ""
        mock_reply.format_for_telegram.return_value = "<b>테스트</b>"

        with (
            patch.object(rm, "is_paused", return_value=False) if False else patch(
                "app.services.growth.monitor_state.is_paused", return_value=False
            ),
            patch(
                "app.services.growth.reply_monitor.ReplyMonitor"
            ) as mock_monitor_cls,
            patch(
                "app.services.growth.reply_monitor.generate_rereply_draft",
                new_callable=AsyncMock,
                return_value="테스트 재답글 초안",
            ),
            patch(
                "app.services.growth._tg_helper.tg_send_with_keyboard",
                new_callable=AsyncMock,
            ) as mock_kb,
            patch(
                "app.services.growth._tg_helper.tg_send",
                new_callable=AsyncMock,
            ) as mock_plain,
        ):
            mock_monitor = AsyncMock()
            mock_monitor.poll_new_replies = AsyncMock(return_value=[mock_reply])
            mock_monitor.mark_processed = MagicMock()
            mock_monitor_cls.return_value = mock_monitor

            await rm.run_reply_monitor()

        mock_kb.assert_called_once()
        mock_plain.assert_not_called()

    @pytest.mark.asyncio
    async def test_keyboard_has_use_and_skip_buttons(self):
        """키보드에 '초안 사용'과 '건너뜀' 버튼이 포함된다."""
        from app.services.growth import reply_monitor as rm

        mock_reply = MagicMock()
        mock_reply.reply_id = "reply_btn_test"
        mock_reply.author_username = "btn_user"
        mock_reply.my_reply_draft = ""
        mock_reply.format_for_telegram.return_value = "msg"

        captured_keyboard = []

        async def capture_keyboard(text, keyboard, **kwargs):
            captured_keyboard.extend(keyboard)
            return True

        with (
            patch("app.services.growth.monitor_state.is_paused", return_value=False),
            patch("app.services.growth.reply_monitor.ReplyMonitor") as mock_monitor_cls,
            patch(
                "app.services.growth.reply_monitor.generate_rereply_draft",
                new_callable=AsyncMock,
                return_value="초안",
            ),
            patch(
                "app.services.growth._tg_helper.tg_send_with_keyboard",
                side_effect=capture_keyboard,
            ),
        ):
            mock_monitor = AsyncMock()
            mock_monitor.poll_new_replies = AsyncMock(return_value=[mock_reply])
            mock_monitor.mark_processed = MagicMock()
            mock_monitor_cls.return_value = mock_monitor

            await rm.run_reply_monitor()

        assert len(captured_keyboard) == 1  # 버튼 한 줄
        row = captured_keyboard[0]
        callback_datas = [btn["callback_data"] for btn in row]
        assert any("reply_use:reply_btn_test" in cd for cd in callback_datas)
        assert any("reply_skip:reply_btn_test" in cd for cd in callback_datas)

    @pytest.mark.asyncio
    async def test_draft_stored_in_pending_before_send(self):
        """tg_send_with_keyboard 호출 전에 _pending_reply_drafts에 초안이 저장된다."""
        from app.services.growth import reply_monitor as rm
        from app.services.growth.reply_monitor import get_pending_draft

        mock_reply = MagicMock()
        mock_reply.reply_id = "reply_store_test"
        mock_reply.author_username = "store_user"
        mock_reply.my_reply_draft = ""
        mock_reply.format_for_telegram.return_value = "msg"

        with (
            patch("app.services.growth.monitor_state.is_paused", return_value=False),
            patch("app.services.growth.reply_monitor.ReplyMonitor") as mock_monitor_cls,
            patch(
                "app.services.growth.reply_monitor.generate_rereply_draft",
                new_callable=AsyncMock,
                return_value="저장 테스트 초안",
            ),
            patch(
                "app.services.growth._tg_helper.tg_send_with_keyboard",
                new_callable=AsyncMock,
                return_value=True,
            ),
        ):
            mock_monitor = AsyncMock()
            mock_monitor.poll_new_replies = AsyncMock(return_value=[mock_reply])
            mock_monitor.mark_processed = MagicMock()
            mock_monitor_cls.return_value = mock_monitor

            await rm.run_reply_monitor()

        entry = get_pending_draft("reply_store_test")
        assert entry is not None
        draft, username = entry
        assert draft == "저장 테스트 초안"
        assert username == "store_user"
