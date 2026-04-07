"""
ContentRequest 모델 테스트
"""
import pytest
from app.models.content_request import ContentRequest, SOURCE_TYPE_MAP


class TestContentRequestNormalization:

    def test_to_source_text_url_only(self):
        req = ContentRequest(source_url="https://example.com/article", source_type="news_link")
        # URL만 있으면 source_text는 빔
        assert req.to_source_text() == ""

    def test_to_source_text_raw_text(self):
        req = ContentRequest(source_type="raw_text", raw_text="한국은행 기준금리 동결")
        assert "한국은행" in req.to_source_text()

    def test_to_source_text_image_extracted(self):
        req = ContentRequest(
            source_type="screenshot_ref",
            image_extracted_text="Screenshot OCR content",
        )
        assert "[Screenshot text]: Screenshot OCR content" in req.to_source_text()

    def test_to_source_text_image_path_no_ocr(self):
        req = ContentRequest(
            source_type="screenshot_ref",
            image_path="/tmp/screenshot.png",
        )
        assert "[Image reference]: /tmp/screenshot.png" in req.to_source_text()

    def test_to_source_text_image_path_skipped_when_ocr_present(self):
        req = ContentRequest(
            source_type="screenshot_ref",
            image_path="/tmp/screenshot.png",
            image_extracted_text="OCR text",
        )
        text = req.to_source_text()
        assert "OCR text" in text
        # image_path는 OCR이 있으면 포함 안 됨
        assert "/tmp/screenshot.png" not in text

    def test_to_source_text_with_note(self):
        req = ContentRequest(source_type="raw_text", raw_text="본문", note="각도 힌트")
        text = req.to_source_text()
        assert "[User note]: 각도 힌트" in text

    def test_to_source_text_with_framing(self):
        req = ContentRequest(
            source_type="raw_text",
            raw_text="본문",
            target_framing="global supply chain angle",
        )
        text = req.to_source_text()
        assert "[International framing hint]: global supply chain angle" in text

    def test_to_source_text_all_fields(self):
        req = ContentRequest(
            source_url="https://example.com",
            source_type="news_link",
            raw_text="본문 텍스트",
            image_extracted_text="스크린샷 OCR",
            note="사용자 메모",
            target_framing="글로벌 각도",
        )
        text = req.to_source_text()
        assert "본문 텍스트" in text
        assert "[Screenshot text]" in text
        assert "[User note]" in text
        assert "[International framing hint]" in text


class TestContentRequestTitle:

    def test_title_from_note(self):
        req = ContentRequest(source_type="observation", note="이번 주 주목할 포인트")
        assert "이번 주 주목할 포인트" in req.to_title()

    def test_title_from_raw_text(self):
        req = ContentRequest(source_type="raw_text", raw_text="한국 출산율 최저 기록")
        assert "한국 출산율" in req.to_title()

    def test_title_from_url(self):
        req = ContentRequest(source_url="https://reuters.com/article", source_type="news_link")
        assert "reuters" in req.to_title()

    def test_title_fallback(self):
        req = ContentRequest(source_type="raw_text")
        title = req.to_title()
        assert "raw_text" in title

    def test_title_max_length(self):
        req = ContentRequest(source_type="raw_text", raw_text="x" * 200)
        assert len(req.to_title()) <= 120


class TestContentRequestHasContent:

    def test_has_content_with_url(self):
        req = ContentRequest(source_url="https://example.com", source_type="news_link")
        assert req.has_content() is True

    def test_has_content_with_raw_text(self):
        req = ContentRequest(source_type="raw_text", raw_text="some text")
        assert req.has_content() is True

    def test_has_content_empty(self):
        req = ContentRequest(source_type="raw_text")
        assert req.has_content() is False

    def test_has_content_note_only(self):
        req = ContentRequest(source_type="observation", note="Just a note")
        assert req.has_content() is True


class TestContentRequestToSourceItemCreate:

    def test_converts_news_link(self):
        req = ContentRequest(
            source_url="https://example.com",
            source_type="news_link",
            raw_text="article text",
        )
        sic = req.to_source_item_create()
        assert sic.source_type == "manual"
        assert sic.url == "https://example.com"

    def test_converts_observation(self):
        req = ContentRequest(source_type="observation", raw_text="daily observation")
        sic = req.to_source_item_create()
        assert sic.source_type == "community_input"

    def test_source_text_includes_all_fields(self):
        req = ContentRequest(
            source_type="raw_text",
            raw_text="본문",
            note="힌트",
        )
        sic = req.to_source_item_create()
        assert "본문" in sic.source_text
        assert "힌트" in sic.source_text

    def test_empty_source_text_uses_title(self):
        req = ContentRequest(
            source_url="https://example.com",
            source_type="news_link",
            note="My note",
        )
        sic = req.to_source_item_create()
        # source_text should not be empty
        assert sic.source_text


class TestSourceTypeMap:

    def test_all_types_mapped(self):
        types = ["news_link", "x_post", "screenshot_ref", "observation", "account_example", "raw_text"]
        for t in types:
            assert t in SOURCE_TYPE_MAP

    def test_observation_maps_to_community(self):
        assert SOURCE_TYPE_MAP["observation"] == "community_input"

    def test_news_link_maps_to_manual(self):
        assert SOURCE_TYPE_MAP["news_link"] == "manual"
