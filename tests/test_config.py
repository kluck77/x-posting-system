"""
설정 테스트
===========
config 로딩, AI 프로바이더 선택 로직, 키 상태 체크를 테스트합니다.
"""

import pytest
from app.config import Settings, validate_settings


class TestSettings:
    def test_default_settings(self):
        s = Settings(_env_file=None)
        assert s.default_language == "en"
        assert s.enable_auto_post_low_risk is False
        assert s.log_level == "INFO"

    def test_no_keys_is_full_mock(self):
        s = Settings(_env_file=None)
        assert s.is_full_mock_mode is True
        assert s.has_any_ai is False

    def test_openai_key_only(self):
        s = Settings(_env_file=None, openai_api_key="test-key")
        assert s.has_openai is True
        assert s.has_anthropic is False
        assert s.has_any_ai is True
        assert s.is_full_mock_mode is False

    def test_anthropic_key_only(self):
        s = Settings(_env_file=None, anthropic_api_key="test-key")
        assert s.has_anthropic is True
        assert s.has_openai is False
        assert s.has_any_ai is True

    def test_all_keys(self):
        s = Settings(
            _env_file=None,
            openai_api_key="k", anthropic_api_key="k",
            gemini_api_key="k", grok_api_key="k", perplexity_api_key="k",
        )
        assert s.has_any_ai is True

    def test_provider_keys_status(self):
        s = Settings(
            _env_file=None,
            openai_api_key="k", anthropic_api_key="k",
        )
        status = s.provider_keys_status()
        assert status["openai"] is True
        assert status["anthropic"] is True
        assert status["gemini"] is False

    def test_effective_draft_provider_mock_by_default(self):
        s = Settings(_env_file=None)
        assert s.get_effective_draft_provider() == "mock"

    def test_effective_draft_provider_openai(self):
        s = Settings(
            _env_file=None,
            openai_api_key="k",
            active_draft_provider="openai",
        )
        assert s.get_effective_draft_provider() == "openai"

    def test_effective_draft_provider_fallback(self):
        """키가 없으면 요청해도 mock으로 fallback"""
        s = Settings(
            _env_file=None,
            active_draft_provider="openai",  # 키 없이 요청
        )
        assert s.get_effective_draft_provider() == "mock"

    def test_effective_draft_provider_anthropic(self):
        s = Settings(
            _env_file=None,
            anthropic_api_key="k",
            active_draft_provider="anthropic",
        )
        assert s.get_effective_draft_provider() == "anthropic"

    def test_ai_status_summary(self):
        s = Settings(_env_file=None, anthropic_api_key="k")
        status = s.ai_status_summary()
        assert status["reviewer"] == "anthropic"
        assert status["draft_writer"] == "mock"
        assert status["research"] == "mock"

    def test_validate_settings_warnings(self):
        s = Settings(_env_file=None)
        warnings = validate_settings(s)
        assert len(warnings) >= 3  # AI + 텔레그램 + X

    def test_x_credentials(self):
        s = Settings(
            _env_file=None,
            x_api_key="k", x_api_secret="s",
            x_access_token="t", x_access_token_secret="ts",
        )
        assert s.has_x_credentials is True

    def test_x_credentials_incomplete(self):
        s = Settings(_env_file=None, x_api_key="k")
        assert s.has_x_credentials is False
