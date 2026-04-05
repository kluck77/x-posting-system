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

    def test_effective_research_gemini(self):
        s = Settings(
            _env_file=None,
            gemini_api_key="k",
            active_research_provider="gemini",
        )
        assert s.get_effective_research_provider() == "gemini"

    def test_effective_research_gemini_fallback(self):
        s = Settings(_env_file=None, active_research_provider="gemini")
        assert s.get_effective_research_provider() == "mock"

    def test_effective_trend_grok(self):
        s = Settings(
            _env_file=None,
            grok_api_key="k",
            active_trend_provider="grok",
        )
        assert s.get_effective_trend_provider() == "grok"

    def test_effective_trend_grok_fallback(self):
        s = Settings(_env_file=None, active_trend_provider="grok")
        assert s.get_effective_trend_provider() == "mock"

    def test_effective_factcheck_perplexity(self):
        s = Settings(
            _env_file=None,
            perplexity_api_key="k",
            active_factcheck_provider="perplexity",
        )
        assert s.get_effective_factcheck_provider() == "perplexity"

    def test_effective_factcheck_perplexity_fallback(self):
        s = Settings(_env_file=None, active_factcheck_provider="perplexity")
        assert s.get_effective_factcheck_provider() == "mock"

    def test_rate_limit_defaults(self):
        """rate limit 기본값 확인"""
        s = Settings(_env_file=None)
        assert s.max_drafts_per_day == 5
        assert s.max_telegram_per_day == 5
        assert s.max_posts_per_day == 10

    def test_rate_limit_env_override(self):
        """환경변수로 rate limit 재정의 가능"""
        s = Settings(_env_file=None, max_drafts_per_day=20, max_posts_per_day=30)
        assert s.max_drafts_per_day == 20
        assert s.max_posts_per_day == 30

    def test_ai_status_summary_all_providers(self):
        s = Settings(
            _env_file=None,
            anthropic_api_key="k", gemini_api_key="k",
            grok_api_key="k", perplexity_api_key="k",
            active_research_provider="gemini",
            active_trend_provider="grok",
            active_factcheck_provider="perplexity",
        )
        status = s.ai_status_summary()
        assert status["research"] == "gemini"
        assert status["trend"] == "grok"
        assert status["factcheck"] == "perplexity"
