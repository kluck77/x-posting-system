"""
콘텐츠 팩 언어 기본값 테스트
============================
한국어 기본 / 영어 명시 시만 영어 규칙을 검증합니다.
"""

from app.services.content_pack import _get_system_prompt, _mock_pack
from app.models.content_request import ContentRequest


class TestContentPackLanguageDefault:
    """콘텐츠 팩 생성 경로에서 한국어가 기본인지 회귀 검증."""

    def test_default_prompt_is_korean(self):
        """language='ko' → 시스템 프롬프트가 한국어."""
        prompt = _get_system_prompt("ko")
        assert "한국어" in prompt
        assert "English-language" not in prompt

    def test_english_prompt_when_explicit(self):
        """language='en' → 시스템 프롬프트가 영어."""
        prompt = _get_system_prompt("en")
        assert "English-language" in prompt

    def test_mock_pack_default_korean(self):
        """language 미지정(기본 ko) → Mock 팩 한국어."""
        req = ContentRequest(raw_text="테스트", source_type="raw_text")
        pack = _mock_pack(req)
        assert "데이터 기반" in pack.main_posts[0]
        assert "Mock 모드" in pack.why_it_matters
        # 영어 잔존 없음
        assert "data-driven" not in pack.main_posts[0]

    def test_mock_pack_english_when_explicit(self):
        """language='en' → Mock 팩 영어."""
        req = ContentRequest(raw_text="test", source_type="raw_text", language="en")
        pack = _mock_pack(req)
        assert "data-driven" in pack.main_posts[0]
        assert "Mock mode" in pack.why_it_matters

    def test_content_request_default_language_is_ko(self):
        """ContentRequest.language 기본값이 'ko'."""
        req = ContentRequest(raw_text="기본", source_type="raw_text")
        assert req.language == "ko"

    def test_prompt_variants_are_different(self):
        """ko/en 프롬프트가 실제로 다른 내용."""
        ko = _get_system_prompt("ko")
        en = _get_system_prompt("en")
        assert ko != en


class TestContentPackPromptQuality:
    """프롬프트 품질 고도화 — few-shot 예시 포함 여부 회귀 검증."""

    def test_ko_prompt_has_good_hook_examples(self):
        """한국어 프롬프트에 좋은 훅 예시가 포함되어 있다."""
        prompt = _get_system_prompt("ko")
        assert "12년 만 최고 금리, 문제는 물가보다 가계부채다" in prompt
        assert "삼성전자 영업이익 10배 반등" in prompt

    def test_ko_prompt_has_bad_hook_examples(self):
        """한국어 프롬프트에 나쁜 훅 예시가 포함되어 있다."""
        prompt = _get_system_prompt("ko")
        assert "한국 기준금리 3.50%, 12년 만 최고" in prompt
        assert "사실 나열" in prompt

    def test_ko_prompt_has_good_why_examples(self):
        """한국어 프롬프트에 좋은 why_it_matters 예시가 포함되어 있다."""
        prompt = _get_system_prompt("ko")
        assert "원화와 외국인 자금 흐름이 먼저 흔들린다" in prompt

    def test_ko_prompt_has_bad_why_examples(self):
        """한국어 프롬프트에 나쁜 why_it_matters 예시가 포함되어 있다."""
        prompt = _get_system_prompt("ko")
        assert "이는 경제에 중요한 의미를 가진다" in prompt

    def test_ko_prompt_has_reply_tone_guidance(self):
        """한국어 프롬프트에 댓글 대화체 지시가 포함되어 있다."""
        prompt = _get_system_prompt("ko")
        assert "대화체" in prompt
        assert "보고서 문체 금지" in prompt

    def test_ko_prompt_has_quote_post_types(self):
        """한국어 프롬프트에 인용 포스트 3유형이 포함되어 있다."""
        prompt = _get_system_prompt("ko")
        assert "반론형" in prompt
        assert "시장영향형" in prompt
        assert "해외설명형" in prompt

    def test_ko_prompt_has_short_version_rules(self):
        """한국어 프롬프트에 짧은 버전 규칙이 포함되어 있다."""
        prompt = _get_system_prompt("ko")
        assert "단순 축약하지 마라" in prompt
        assert "훅형 압축문" in prompt
