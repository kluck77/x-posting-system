"""daytime_alert_service.try_daytime_alert 의 inline keyboard +
pending article register 검증 (Bug 2 fix).

기존 news_monitor.try_breaking_alert 와 동일한 callback_data 형식
(news_draft:{hash} / news_skip:{hash}) 으로 재사용해 _handle_news_callback
이 그대로 처리. news_monitor 의 private registry (_pending_articles +
_article_hash) 를 same-package 로 import.
"""
from __future__ import annotations

import asyncio
import json
from unittest.mock import patch, AsyncMock, MagicMock


def _drain_registry():
    """테스트 격리 — pending registry clear."""
    from app.services.news_monitor import _pending_articles
    _pending_articles.clear()


class TestDaytimeAlertInlineKeyboard:
    def setup_method(self):
        _drain_registry()

    def _patch_settings_and_run(self, **alert_kwargs) -> dict:
        """try_daytime_alert 를 mocked httpx 로 실행하고 sent payload 반환."""
        from app.services import daytime_alert_service as das

        captured: dict = {}

        class _MockResp:
            status_code = 200
            def raise_for_status(self): pass
            def json(self): return {"ok": True}

        class _MockClient:
            def __init__(self, *a, **k): pass
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False
            async def post(self, url, data=None, **k):
                captured["url"] = url
                captured["data"] = data
                return _MockResp()

        # daytime alert 발송 조건 우회 — should_send_daytime_alert / score 모두
        # bypass 후 directly 카드 전송 단계 검증.
        with patch.object(das, "settings", MagicMock(
            has_telegram_config=True,
            telegram_bot_token="TEST_TOKEN",
            telegram_chat_id="123",
        )), patch.object(das, "httpx", MagicMock(AsyncClient=_MockClient)):
            with patch.object(das, "should_send_daytime_alert", return_value=True):
                # score_candidate 도 mock
                # score_candidate 는 float / int score 1 개 반환 (코드에서
                # f"{score:.0f}" 로 포맷됨)
                with patch(
                    "app.services.top5_briefing_service.score_candidate",
                    return_value=99.0,
                ):
                    asyncio.run(das.try_daytime_alert(**alert_kwargs))

        return captured

    def test_payload_contains_inline_keyboard(self):
        out = self._patch_settings_and_run(
            title="UAE OPEC+ 탈퇴 발표",
            body="2026 년 5 월 1 일 효력. 사우디 영향력 축소.",
            url="https://www.news1.kr/world/usa-canada/6152007",
            topic_domain="economy",
            matched_keywords=["OPEC", "UAE", "원유"],
        )
        data = out.get("data", {})
        assert "reply_markup" in data, (
            "daytime alert payload 에 reply_markup 누락 — 사용자가 초안 "
            "생성 버튼 못 누름"
        )
        keyboard = json.loads(data["reply_markup"])
        assert "inline_keyboard" in keyboard
        rows = keyboard["inline_keyboard"]
        assert len(rows) >= 1
        buttons = rows[0]
        # 3 버튼 (URL 있을 때): 원문 / 초안 생성 / 3h 무시
        button_texts = [b.get("text", "") for b in buttons]
        assert any("원문" in t for t in button_texts)
        assert any("초안 생성" in t for t in button_texts)
        assert any("무시" in t for t in button_texts)

    def test_callback_data_news_draft_format(self):
        out = self._patch_settings_and_run(
            title="UAE OPEC+ 탈퇴",
            body="2026 핵심 사실",
            url="https://example.com/article",
            topic_domain="economy",
            matched_keywords=["OPEC"],
        )
        kb = json.loads(out["data"]["reply_markup"])
        buttons = kb["inline_keyboard"][0]
        cb_data = [b.get("callback_data", "") for b in buttons]
        # 기존 _handle_news_callback 와 호환 형식: news_draft:{hash} / news_skip:{hash}
        assert any(d.startswith("news_draft:") for d in cb_data), (
            "초안 생성 callback_data 가 'news_draft:{hash}' 형식이어야 "
            "기존 _handle_news_callback 이 처리 가능"
        )
        assert any(d.startswith("news_skip:") for d in cb_data)

    def test_pending_article_registered(self):
        # daytime alert 가 news_monitor 의 _pending_articles 에 등록되어
        # _handle_news_callback 의 get_pending_article(hash) 가 작동
        from app.services.news_monitor import _pending_articles
        before = len(_pending_articles)
        out = self._patch_settings_and_run(
            title="UAE OPEC+ 탈퇴 발표",
            body="2026 년 5 월 1 일 효력",
            url="https://news.example.com/uae-opec",
            topic_domain="economy",
            matched_keywords=["OPEC"],
        )
        after = len(_pending_articles)
        assert after == before + 1, (
            "daytime alert 가 _pending_articles 에 1 개 article 등록해야 함"
        )
        # callback_data 의 hash 와 registry 의 키 일치
        kb = json.loads(out["data"]["reply_markup"])
        buttons = kb["inline_keyboard"][0]
        draft_btn = next(b for b in buttons
                         if b.get("callback_data", "").startswith("news_draft:"))
        ah = draft_btn["callback_data"].split(":", 1)[1]
        assert ah in _pending_articles
        # 등록된 article shape 검증 (title / url / summary)
        reg = _pending_articles[ah]
        assert reg.get("title") == "UAE OPEC+ 탈퇴 발표"
        assert reg.get("url") == "https://news.example.com/uae-opec"
        assert "2026 년 5 월 1 일" in reg.get("summary", "")

    def test_no_url_keyboard_still_has_draft_skip(self):
        # url 이 없어도 (드물지만) 초안 생성 / 무시 버튼은 있어야 함
        out = self._patch_settings_and_run(
            title="제목만 있음",
            body="짧은 본문",
            url=None,
            topic_domain="economy",
            matched_keywords=["test"],
        )
        kb = json.loads(out["data"]["reply_markup"])
        buttons = kb["inline_keyboard"][0]
        cb_data = [b.get("callback_data", "") for b in buttons]
        assert any(d.startswith("news_draft:") for d in cb_data)
        assert any(d.startswith("news_skip:") for d in cb_data)
        # url 없으면 원문 버튼은 미생성
        urls = [b.get("url") for b in buttons if "url" in b]
        assert len(urls) == 0


class TestNewsMonitorAlertFlowUnchanged:
    """news_monitor.try_breaking_alert 의 callback_data 형식 / pending
    registry 가 daytime_alert fix 로 깨지지 않는지 검증."""

    def test_news_monitor_callback_format_intact(self):
        # news_monitor 가 여전히 news_draft / news_skip 형식 사용
        import inspect
        from app.services import news_monitor
        src = inspect.getsource(news_monitor)
        assert '"news_draft:' in src or "'news_draft:" in src
        assert '"news_skip:' in src or "'news_skip:" in src

    def test_pending_registry_shape_intact(self):
        # _pending_articles dict + _article_hash 함수 + _PENDING_ARTICLES_MAX
        # 상수 모두 import 가능 (daytime_alert 의존)
        from app.services.news_monitor import (
            _pending_articles, _article_hash, _PENDING_ARTICLES_MAX,
        )
        assert isinstance(_pending_articles, dict)
        assert callable(_article_hash)
        assert isinstance(_PENDING_ARTICLES_MAX, int)
        # _article_hash 는 string in / string out
        h = _article_hash("https://example.com/test")
        assert isinstance(h, str) and len(h) > 0
