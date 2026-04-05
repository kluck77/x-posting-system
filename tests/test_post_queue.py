"""
PostQueue 승인 게이트 테스트.

핵심 검증:
1. try_publish_next()는 _publish_to_x()를 직접 호출하지 않는다.
2. 슬롯이 열리면 _send_approval_notification()만 호출한다.
3. approve_queued_post()는 _publish_to_x()를 호출한다.
4. notified_at이 이미 설정된 게시물은 중복 알림을 보내지 않는다.
"""

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from app.services.growth.post_queue import PostQueue, QueuedPost


# ---------------------------------------------------------------------------
# 헬퍼
# ---------------------------------------------------------------------------

def _make_queue() -> PostQueue:
    """파일 I/O 없이 빈 PostQueue 생성."""
    q = PostQueue.__new__(PostQueue)
    q._queue = []
    q._last_published = None
    return q


def _add_post(queue: PostQueue, text: str = "테스트 게시물") -> QueuedPost:
    post = QueuedPost(text=text)
    queue._queue.append(post)
    return post


# ---------------------------------------------------------------------------
# 1. try_publish_next() — _publish_to_x() 직접 호출 없음
# ---------------------------------------------------------------------------

class TestTryPublishNextNoAutoPost:
    """슬롯이 열려도 _publish_to_x()를 직접 호출하지 않는다."""

    @pytest.mark.asyncio
    async def test_does_not_call_publish_to_x_when_slot_opens(self):
        queue = _make_queue()
        post = _add_post(queue)

        with (
            patch.object(queue, "_is_optimal_slot_now", return_value=True),
            patch.object(queue, "_can_publish_now", return_value=True),
            patch.object(queue, "_publish_to_x", new_callable=AsyncMock) as mock_publish,
            patch.object(queue, "_send_approval_notification", new_callable=AsyncMock),
            patch.object(queue, "_save"),
        ):
            result = await queue.try_publish_next()

        mock_publish.assert_not_called()
        assert result is post

    @pytest.mark.asyncio
    async def test_sends_approval_notification_when_slot_opens(self):
        queue = _make_queue()
        _add_post(queue)

        with (
            patch.object(queue, "_is_optimal_slot_now", return_value=True),
            patch.object(queue, "_can_publish_now", return_value=True),
            patch.object(queue, "_send_approval_notification", new_callable=AsyncMock) as mock_notify,
            patch.object(queue, "_save"),
        ):
            result = await queue.try_publish_next()

        mock_notify.assert_called_once()
        assert result is not None

    @pytest.mark.asyncio
    async def test_sets_notified_at_after_notification(self):
        queue = _make_queue()
        post = _add_post(queue)
        assert post.notified_at is None

        with (
            patch.object(queue, "_is_optimal_slot_now", return_value=True),
            patch.object(queue, "_can_publish_now", return_value=True),
            patch.object(queue, "_send_approval_notification", new_callable=AsyncMock),
            patch.object(queue, "_save"),
        ):
            await queue.try_publish_next()

        assert post.notified_at is not None

    @pytest.mark.asyncio
    async def test_returns_none_when_not_optimal_slot(self):
        queue = _make_queue()
        _add_post(queue)

        with patch.object(queue, "_is_optimal_slot_now", return_value=False):
            result = await queue.try_publish_next()

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_interval_not_met(self):
        queue = _make_queue()
        _add_post(queue)

        with (
            patch.object(queue, "_is_optimal_slot_now", return_value=True),
            patch.object(queue, "_can_publish_now", return_value=False),
        ):
            result = await queue.try_publish_next()

        assert result is None


# ---------------------------------------------------------------------------
# 2. 중복 알림 방지
# ---------------------------------------------------------------------------

class TestNoDuplicateNotification:
    """notified_at이 이미 설정된 게시물은 다시 알림을 보내지 않는다."""

    @pytest.mark.asyncio
    async def test_skips_already_notified_post(self):
        queue = _make_queue()
        post = _add_post(queue)
        post.notified_at = datetime.now(timezone.utc)  # 이미 알림 발송됨

        with (
            patch.object(queue, "_is_optimal_slot_now", return_value=True),
            patch.object(queue, "_can_publish_now", return_value=True),
            patch.object(queue, "_send_approval_notification", new_callable=AsyncMock) as mock_notify,
        ):
            result = await queue.try_publish_next()

        mock_notify.assert_not_called()
        assert result is None


# ---------------------------------------------------------------------------
# 3. approve_queued_post() — _publish_to_x() 호출
# ---------------------------------------------------------------------------

class TestApproveQueuedPost:
    """approve_queued_post()는 _publish_to_x()를 호출해 실제 발행한다."""

    @pytest.mark.asyncio
    async def test_calls_publish_to_x_on_approve(self):
        queue = _make_queue()
        post = _add_post(queue)
        post_key = post.added_at.isoformat()

        with (
            patch.object(queue, "_publish_to_x", new_callable=AsyncMock, return_value="tweet_123") as mock_publish,
            patch.object(queue, "_save"),
        ):
            result = await queue.approve_queued_post(post_key)

        mock_publish.assert_called_once_with(post)
        assert result is post

    @pytest.mark.asyncio
    async def test_marks_post_as_published(self):
        queue = _make_queue()
        post = _add_post(queue)
        post_key = post.added_at.isoformat()

        with (
            patch.object(queue, "_publish_to_x", new_callable=AsyncMock, return_value="tweet_123"),
            patch.object(queue, "_save"),
        ):
            await queue.approve_queued_post(post_key)

        assert post.published_at is not None
        assert post.post_id == "tweet_123"

    @pytest.mark.asyncio
    async def test_returns_none_for_unknown_key(self):
        queue = _make_queue()
        _add_post(queue)

        result = await queue.approve_queued_post("not-a-real-key")

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_for_already_published_post(self):
        queue = _make_queue()
        post = _add_post(queue)
        post.published_at = datetime.now(timezone.utc)  # 이미 발행됨
        post_key = post.added_at.isoformat()

        with patch.object(queue, "_publish_to_x", new_callable=AsyncMock) as mock_publish:
            result = await queue.approve_queued_post(post_key)

        mock_publish.assert_not_called()
        assert result is None

    @pytest.mark.asyncio
    async def test_updates_last_published_on_success(self):
        queue = _make_queue()
        post = _add_post(queue)
        post_key = post.added_at.isoformat()
        assert queue._last_published is None

        with (
            patch.object(queue, "_publish_to_x", new_callable=AsyncMock, return_value="tweet_456"),
            patch.object(queue, "_save"),
        ):
            await queue.approve_queued_post(post_key)

        assert queue._last_published is not None


# ---------------------------------------------------------------------------
# 4. remove_pending() — 운영자 visible position 기준 제거
# ---------------------------------------------------------------------------

class TestRemovePending:
    """/queue remove <n> 의 핵심 로직: remove_pending(position) 검증."""

    def test_removes_correct_item_by_position(self):
        """position 1은 첫 번째 대기 게시물을 제거한다."""
        queue = _make_queue()
        post1 = _add_post(queue, "첫 번째")
        post2 = _add_post(queue, "두 번째")
        post3 = _add_post(queue, "세 번째")

        with patch.object(queue, "_save"):
            removed = queue.remove_pending(1)

        assert removed is post1
        assert post1 not in queue._queue
        assert post2 in queue._queue
        assert post3 in queue._queue

    def test_removes_middle_item(self):
        """position 2는 두 번째 대기 게시물을 제거한다."""
        queue = _make_queue()
        post1 = _add_post(queue, "첫 번째")
        post2 = _add_post(queue, "두 번째")
        post3 = _add_post(queue, "세 번째")

        with patch.object(queue, "_save"):
            removed = queue.remove_pending(2)

        assert removed is post2
        assert post1 in queue._queue
        assert post2 not in queue._queue
        assert post3 in queue._queue

    def test_published_posts_not_counted_in_position(self):
        """발행 완료된 게시물은 position 카운트에 포함되지 않는다."""
        queue = _make_queue()
        published = _add_post(queue, "발행 완료")
        published.published_at = datetime.now(timezone.utc)
        pending1 = _add_post(queue, "대기 1")
        pending2 = _add_post(queue, "대기 2")

        with patch.object(queue, "_save"):
            removed = queue.remove_pending(1)

        # position 1 = pending1 (발행 완료 게시물은 건너뜀)
        assert removed is pending1
        assert published in queue._queue  # 발행 완료 게시물은 그대로
        assert pending2 in queue._queue

    def test_returns_none_for_empty_queue(self):
        """큐가 비어 있으면 None을 반환한다."""
        queue = _make_queue()
        result = queue.remove_pending(1)
        assert result is None

    def test_returns_none_for_position_zero(self):
        """position 0은 유효하지 않다 (1-indexed)."""
        queue = _make_queue()
        _add_post(queue)
        result = queue.remove_pending(0)
        assert result is None

    def test_returns_none_for_position_out_of_range(self):
        """position이 대기 개수를 초과하면 None을 반환한다."""
        queue = _make_queue()
        _add_post(queue, "하나뿐")

        result = queue.remove_pending(2)
        assert result is None

    def test_returns_none_for_negative_position(self):
        """음수 position은 None을 반환한다."""
        queue = _make_queue()
        _add_post(queue)
        result = queue.remove_pending(-1)
        assert result is None

    def test_save_called_on_successful_remove(self):
        """제거 성공 시 _save()가 호출된다."""
        queue = _make_queue()
        _add_post(queue, "저장 테스트")

        with patch.object(queue, "_save") as mock_save:
            queue.remove_pending(1)

        mock_save.assert_called_once()

    def test_save_not_called_on_failed_remove(self):
        """제거 실패 시 _save()가 호출되지 않는다."""
        queue = _make_queue()

        with patch.object(queue, "_save") as mock_save:
            queue.remove_pending(1)

        mock_save.assert_not_called()
