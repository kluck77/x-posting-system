"""
ContentPack 생성 및 파싱 테스트
"""
import json
import pytest
from app.services.content_pack import (
    ContentPack,
    _parse_response,
    _mock_pack,
    _ensure_list,
)
from app.models.content_request import ContentRequest


class TestContentPackDataclass:

    def test_default_fields(self):
        pack = ContentPack()
        assert pack.main_posts == []
        assert pack.short_version == ""
        assert pack.reply_drafts == []
        assert pack.quote_post_drafts == []
        assert pack.thread_option is None
        assert pack.risk_flags == []
        assert pack.topic_tags == []
        assert pack.why_it_matters == ""
        assert pack.style_warnings == []

    def test_is_valid_empty(self):
        pack = ContentPack()
        assert pack.is_valid() is False

    def test_is_valid_with_main_and_why(self):
        pack = ContentPack(
            main_posts=["Post A", "Post B", "Post C"],
            why_it_matters="Because international investors care.",
        )
        assert pack.is_valid() is True

    def test_is_valid_missing_why(self):
        pack = ContentPack(main_posts=["Post A"])
        assert pack.is_valid() is False

    def test_topic_tags_str_empty(self):
        pack = ContentPack()
        assert pack.topic_tags_str() == ""

    def test_topic_tags_str(self):
        pack = ContentPack(topic_tags=["economy", "BOK"])
        assert pack.topic_tags_str() == "#economy #BOK"


class TestParseResponse:

    def _valid_json(self) -> str:
        data = {
            "main_posts": [
                "Hook A\n\nBody A text here.",
                "Hook B\n\nBody B text here.",
                "Hook C\n\nBody C text here.",
            ],
            "short_version": "Short punchy version.",
            "reply_drafts": ["Reply 1", "Reply 2", "Reply 3"],
            "quote_post_drafts": ["Quote 1", "Quote 2"],
            "thread_option": "1/ Thread start...",
            "risk_flags": ["Politically charged"],
            "topic_tags": ["economy", "BOK"],
            "why_it_matters": "This affects global bond markets.",
            "style_warnings": [],
        }
        return json.dumps(data)

    def test_valid_response(self):
        raw = self._valid_json()
        pack = _parse_response(raw)
        assert pack is not None
        assert len(pack.main_posts) == 3
        assert pack.short_version == "Short punchy version."
        assert pack.why_it_matters == "This affects global bond markets."
        assert pack.thread_option == "1/ Thread start..."
        assert "BOK" in pack.topic_tags

    def test_missing_thread_option_none(self):
        data = json.loads(self._valid_json())
        data["thread_option"] = None
        pack = _parse_response(json.dumps(data))
        assert pack is not None
        assert pack.thread_option is None

    def test_main_posts_capped_at_3(self):
        data = json.loads(self._valid_json())
        data["main_posts"] = ["P1", "P2", "P3", "P4", "P5"]
        pack = _parse_response(json.dumps(data))
        assert len(pack.main_posts) == 3

    def test_reply_drafts_capped_at_3(self):
        data = json.loads(self._valid_json())
        data["reply_drafts"] = ["R1", "R2", "R3", "R4"]
        pack = _parse_response(json.dumps(data))
        assert len(pack.reply_drafts) == 3

    def test_quote_posts_capped_at_2(self):
        data = json.loads(self._valid_json())
        data["quote_post_drafts"] = ["Q1", "Q2", "Q3"]
        pack = _parse_response(json.dumps(data))
        assert len(pack.quote_post_drafts) == 2

    def test_invalid_json_returns_none(self):
        pack = _parse_response("not valid json at all {{")
        assert pack is None

    def test_json_in_markdown_block(self):
        raw = '```json\n' + self._valid_json() + '\n```'
        pack = _parse_response(raw)
        assert pack is not None
        assert pack.is_valid()

    def test_missing_optional_fields(self):
        data = {
            "main_posts": ["Post A", "Post B", "Post C"],
            "short_version": "Short",
            "reply_drafts": [],
            "quote_post_drafts": [],
            "why_it_matters": "Global significance.",
        }
        pack = _parse_response(json.dumps(data))
        assert pack is not None
        assert pack.risk_flags == []
        assert pack.style_warnings == []
        assert pack.thread_option is None

    def test_non_string_items_coerced(self):
        data = {
            "main_posts": [1, "Post B", None],
            "short_version": "Short",
            "reply_drafts": [],
            "quote_post_drafts": [],
            "why_it_matters": "Matters.",
        }
        pack = _parse_response(json.dumps(data))
        assert pack is not None
        # None filtered out, 1 coerced to "1"
        assert len(pack.main_posts) <= 3


class TestMockPack:

    def test_mock_returns_valid_pack(self):
        req = ContentRequest(source_type="raw_text", raw_text="한국은행 금리 동결")
        pack = _mock_pack(req)
        assert pack.is_valid()
        assert len(pack.main_posts) == 3
        assert len(pack.reply_drafts) == 3
        assert len(pack.quote_post_drafts) == 2
        assert pack.thread_option is not None

    def test_mock_preserves_source_url(self):
        req = ContentRequest(
            source_url="https://example.com",
            source_type="news_link",
            raw_text="article content",
        )
        pack = _mock_pack(req)
        assert pack.source_url == "https://example.com"
        assert pack.source_type == "news_link"

    def test_mock_has_risk_flags(self):
        req = ContentRequest(source_type="raw_text", raw_text="test")
        pack = _mock_pack(req)
        assert len(pack.risk_flags) > 0


class TestEnsureList:

    def test_none_returns_empty(self):
        assert _ensure_list(None, 3) == []

    def test_string_returns_empty(self):
        assert _ensure_list("not a list", 3) == []

    def test_list_truncated(self):
        assert _ensure_list(["a", "b", "c", "d"], 3) == ["a", "b", "c"]

    def test_no_max(self):
        result = _ensure_list(["a", "b", "c", "d"], None)
        assert len(result) == 4

    def test_filters_empty_strings(self):
        result = _ensure_list(["a", "", "c"], None)
        assert "" not in result

    def test_coerces_to_string(self):
        result = _ensure_list([1, 2, 3], None)
        assert result == ["1", "2", "3"]


class TestSendContentPackMessages:

    def _make_pack(self) -> ContentPack:
        return ContentPack(
            main_posts=["Hook A\n\nBody A", "Hook B\n\nBody B", "Hook C\n\nBody C"],
            short_version="Short version.",
            reply_drafts=["Reply 1", "Reply 2", "Reply 3"],
            quote_post_drafts=["Quote 1", "Quote 2"],
            thread_option="Thread start...",
            risk_flags=["Sensitive topic"],
            topic_tags=["economy"],
            why_it_matters="International relevance.",
            style_warnings=["Similar to last week"],
        )

    def test_returns_list_of_dicts(self):
        from app.services.telegram_service import send_content_pack_messages
        messages = send_content_pack_messages(self._make_pack())
        assert isinstance(messages, list)
        assert len(messages) > 0
        for m in messages:
            assert "text" in m
            assert "pack_index" in m

    def test_overview_message_first(self):
        from app.services.telegram_service import send_content_pack_messages
        messages = send_content_pack_messages(self._make_pack())
        first = messages[0]
        assert "콘텐츠 팩" in first["text"]
        assert first["pack_index"] is None

    def test_main_posts_have_indices(self):
        from app.services.telegram_service import send_content_pack_messages
        messages = send_content_pack_messages(self._make_pack())
        indexed = [m for m in messages if m.get("pack_index") is not None]
        # 3 main posts + 1 short version
        assert len(indexed) == 4

    def test_short_version_index_10(self):
        from app.services.telegram_service import send_content_pack_messages
        messages = send_content_pack_messages(self._make_pack())
        short_msgs = [m for m in messages if m.get("pack_index") == 10]
        assert len(short_msgs) == 1

    def test_reply_drafts_no_index(self):
        from app.services.telegram_service import send_content_pack_messages
        messages = send_content_pack_messages(self._make_pack())
        reply_msgs = [m for m in messages if "댓글 초안" in m["text"]]
        assert len(reply_msgs) == 1
        assert reply_msgs[0]["pack_index"] is None

    def test_risk_flags_in_overview(self):
        from app.services.telegram_service import send_content_pack_messages
        messages = send_content_pack_messages(self._make_pack())
        overview = messages[0]["text"]
        assert "Sensitive topic" in overview

    def test_why_it_matters_in_overview(self):
        from app.services.telegram_service import send_content_pack_messages
        messages = send_content_pack_messages(self._make_pack())
        overview = messages[0]["text"]
        assert "International relevance" in overview

    def test_thread_option_message_present(self):
        from app.services.telegram_service import send_content_pack_messages
        messages = send_content_pack_messages(self._make_pack())
        thread_msgs = [m for m in messages if "스레드" in m["text"]]
        assert len(thread_msgs) >= 1

    def test_no_thread_option_no_thread_message(self):
        from app.services.telegram_service import send_content_pack_messages
        pack = self._make_pack()
        pack.thread_option = None
        messages = send_content_pack_messages(pack)
        thread_msgs = [m for m in messages if "스레드" in m.get("text", "") and "Thread" in m.get("text", "")]
        assert len(thread_msgs) == 0
