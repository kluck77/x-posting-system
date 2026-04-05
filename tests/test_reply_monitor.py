"""
ReplyMonitor 안정성 테스트
============================
post_reply() 예외 처리 및 rate limit 대응을 검증한다.
"""

import pytest
import httpx
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
