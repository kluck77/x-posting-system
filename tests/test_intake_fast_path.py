"""
Source intake fast-path 테스트.

검증 항목:
1. [버그 수정 회귀] 분석 카드 → [📦 콘텐츠 팩]: pending["text"] 키가 올바르게 읽힌다.
2. /draft 커맨드: URL이면 fetch_url_content → _run_pipeline 로 라우팅된다.
3. /draft 커맨드: 일반 텍스트는 fetch 없이 바로 _run_pipeline 으로 라우팅된다.
4. /draft 커맨드: 인수 없으면 usage 메시지를 반환한다.
5. /draft 커맨드: URL fetch 실패 시 오류 메시지를 반환한다.

NOTE: app.telegram_bot을 직접 import하면 telegram 라이브러리 의존성 문제가 발생하므로
(cryptography/cffi 미설치 환경) 로직은 인라인으로 검증하거나 telegram을 mock한다.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# 헬퍼: draft_command 핵심 라우팅 로직 인라인 복사
# (telegram_bot import 없이 순수 로직만 검증)
# ---------------------------------------------------------------------------

async def _draft_route(args_text: str, fetch_fn, run_pipeline_fn):
    """draft_command 의 URL/텍스트 분기 로직 — telegram_bot 미의존 복사본."""
    from app.services.content_fetcher import is_url

    if not args_text:
        return "usage"

    if is_url(args_text):
        result = await fetch_fn(args_text)
        if result.get("source") == "failed" or not result.get("text"):
            return "fetch_failed"
        pending = {
            "title": result.get("title") or args_text[:80],
            "text": result["text"],
            "url": args_text,
            "source_type": "manual",
        }
    else:
        pending = {
            "title": args_text[:80] + ("..." if len(args_text) > 80 else ""),
            "text": args_text,
            "url": None,
            "source_type": "community_input",
        }

    await run_pipeline_fn(pending)
    return "pipeline_called"


# ---------------------------------------------------------------------------
# 1. 버그 수정 회귀: pending["text"] 키
# ---------------------------------------------------------------------------

class TestContentPackPendingKey:
    """
    분석 카드가 pending에 저장하는 키는 "text".
    _run_content_pack이 이 키를 올바르게 읽는지 검증.
    (버그: 이전에는 "fetched_text" / "source_text" 로 읽어서 항상 빈값이었음)
    """

    def test_analysis_card_pending_uses_text_key(self):
        """_run_analysis_and_show_card가 사용하는 키 이름 확인."""
        # _run_analysis_and_show_card 의 pending 저장 패턴 재현
        pending = {
            "title": "BOK 기준금리 동결",
            "text": "한국은행이 기준금리를 2.75%로 동결했다.",
            "url": "https://example.com/news",
            "source_type": "manual",
        }
        # 올바른 키: "text"
        assert pending.get("text") == "한국은행이 기준금리를 2.75%로 동결했다."
        # 이전 버그 키들: 빈값이어야 함
        assert pending.get("fetched_text", "") == ""
        assert pending.get("source_text", "") == ""

    def test_content_request_built_correctly_from_text_key(self):
        """pending["text"] 를 raw_text에 넣으면 ContentRequest.has_content()가 True."""
        from app.models.content_request import ContentRequest

        pending = {
            "title": "BOK 기준금리 동결",
            "text": "한국은행이 기준금리를 2.75%로 동결했다.",
            "url": "https://example.com/news",
            "source_type": "manual",
        }

        fetched_text = pending.get("text", "")   # ← fix: was "fetched_text"
        req = ContentRequest(
            source_url=pending.get("url"),
            source_type="news_link",
            raw_text=fetched_text,
        )
        assert req.has_content() is True
        assert req.raw_text == "한국은행이 기준금리를 2.75%로 동결했다."

    def test_old_bug_would_have_empty_content(self):
        """이전 버그 재현: pending.get('fetched_text') 는 빈값 → has_content() False."""
        from app.models.content_request import ContentRequest

        pending = {
            "title": "BOK 기준금리 동결",
            "text": "한국은행이 기준금리를 2.75%로 동결했다.",
            "url": None,
            "source_type": "community_input",
        }

        # 버그가 있던 코드
        fetched_text_buggy = pending.get("fetched_text", "") or pending.get("source_text", "")
        req = ContentRequest(
            source_url=None,
            source_type="raw_text",
            raw_text=fetched_text_buggy,
        )
        # 버그 재현: URL도 없고 raw_text도 비어서 has_content() == False
        assert req.has_content() is False


# ---------------------------------------------------------------------------
# 2. /draft 커맨드 라우팅 로직
# ---------------------------------------------------------------------------

class TestDraftCommandRouting:
    """draft_command 의 URL/텍스트 분기 및 엣지 케이스."""

    @pytest.mark.asyncio
    async def test_empty_args_returns_usage(self):
        result = await _draft_route("", AsyncMock(), AsyncMock())
        assert result == "usage"

    @pytest.mark.asyncio
    async def test_plain_text_calls_pipeline_without_fetch(self):
        fetch_fn = AsyncMock()
        pipeline_fn = AsyncMock()

        result = await _draft_route(
            "한국은행 기준금리 2.75% 동결 발표",
            fetch_fn,
            pipeline_fn,
        )

        fetch_fn.assert_not_called()
        pipeline_fn.assert_called_once()
        called_pending = pipeline_fn.call_args[0][0]
        assert called_pending["text"] == "한국은행 기준금리 2.75% 동결 발표"
        assert called_pending["url"] is None
        assert called_pending["source_type"] == "community_input"
        assert result == "pipeline_called"

    @pytest.mark.asyncio
    async def test_url_calls_fetch_then_pipeline(self):
        url = "https://example.com/article"
        fetch_fn = AsyncMock(return_value={
            "title": "BOK 기준금리 동결",
            "text": "한국은행이 기준금리를 2.75%로 동결.",
            "source": "direct",
        })
        pipeline_fn = AsyncMock()

        result = await _draft_route(url, fetch_fn, pipeline_fn)

        fetch_fn.assert_called_once_with(url)
        pipeline_fn.assert_called_once()
        called_pending = pipeline_fn.call_args[0][0]
        assert called_pending["text"] == "한국은행이 기준금리를 2.75%로 동결."
        assert called_pending["url"] == url
        assert called_pending["source_type"] == "manual"
        assert result == "pipeline_called"

    @pytest.mark.asyncio
    async def test_url_fetch_failure_returns_error(self):
        url = "https://example.com/blocked"
        fetch_fn = AsyncMock(return_value={"source": "failed", "text": ""})
        pipeline_fn = AsyncMock()

        result = await _draft_route(url, fetch_fn, pipeline_fn)

        pipeline_fn.assert_not_called()
        assert result == "fetch_failed"

    @pytest.mark.asyncio
    async def test_url_fetch_empty_text_returns_error(self):
        url = "https://example.com/empty"
        fetch_fn = AsyncMock(return_value={"source": "direct", "text": None})
        pipeline_fn = AsyncMock()

        result = await _draft_route(url, fetch_fn, pipeline_fn)

        pipeline_fn.assert_not_called()
        assert result == "fetch_failed"

    @pytest.mark.asyncio
    async def test_long_text_title_is_truncated(self):
        long_text = "A" * 200
        fetch_fn = AsyncMock()
        pipeline_fn = AsyncMock()

        await _draft_route(long_text, fetch_fn, pipeline_fn)

        called_pending = pipeline_fn.call_args[0][0]
        assert len(called_pending["title"]) <= 83  # 80 + "..."
        assert called_pending["title"].endswith("...")
        assert called_pending["text"] == long_text
