"""
설정 관리 모듈
=============
.env 파일에서 환경변수를 읽어오고, 앱 전체에서 사용할 설정값을 관리합니다.

5-역할 AI 아키텍처:
  - ChatGPT (OpenAI): 드래프트 작성 (빠른 초안, 톤 조정)
  - Claude (Anthropic): 아키텍트 & 리뷰어 (리스크 판단, 최종 다듬기)
  - Gemini (Google): 리서치 & 분석 [미래]
  - Grok (xAI): 트렌드 탐지 [미래]
  - Perplexity: 팩트체크 & 출처 [미래]
"""

from pathlib import Path
from pydantic_settings import BaseSettings
from pydantic import Field
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).parent.parent
ENV_FILE = PROJECT_ROOT / ".env"
load_dotenv(ENV_FILE)


class Settings(BaseSettings):
    """앱의 모든 설정값."""

    # --- AI 프로바이더 키 ---
    # 기존
    openai_api_key: str = Field(default="", description="OpenAI API 키 (Draft Writer)")
    anthropic_api_key: str = Field(default="", description="Anthropic Claude (Reviewer + Draft)")
    gemini_api_key: str = Field(default="", description="Google Gemini (Researcher)")
    grok_api_key: str = Field(default="", description="xAI Grok (TrendHunter) — x.ai 에서 발급")
    perplexity_api_key: str = Field(default="", description="Perplexity (FactChecker)")
    # 신규 — 키 입력 시 자동 활성화
    deepseek_api_key: str = Field(default="", description="DeepSeek (DraftWriter/Reviewer) — platform.deepseek.com")
    groq_api_key: str = Field(default="", description="Groq LPU 고속 (FastWriter) — console.groq.com (무료)")
    tavily_api_key: str = Field(default="", description="Tavily WebSearch (컨텍스트 보강) — tavily.com (1000회/월 무료)")
    mistral_api_key: str = Field(default="", description="Mistral AI (Reviewer 대안, GDPR) — console.mistral.ai")
    together_api_key: str = Field(default="", description="Together AI (Llama 405B DraftWriter) — api.together.xyz")

    # --- Naver Open API (뉴스 검색, 무료) ---
    naver_client_id: str = Field(default="", description="Naver API Client ID (뉴스 검색)")
    naver_client_secret: str = Field(default="", description="Naver API Client Secret")

    # --- 활성 프로바이더 선택 ---
    active_draft_provider: str = Field(default="mock", description="초안 작성 프로바이더")
    active_research_provider: str = Field(default="mock", description="리서치 프로바이더")
    active_trend_provider: str = Field(default="mock", description="트렌드 탐지 프로바이더")
    active_factcheck_provider: str = Field(default="mock", description="팩트체크 프로바이더")

    # --- 텔레그램 ---
    telegram_bot_token: str = Field(default="", description="텔레그램 봇 토큰")
    telegram_chat_id: str = Field(default="", description="텔레그램 채팅 ID")

    # --- X (트위터) API ---
    x_bearer_token: str = Field(default="", description="X Bearer Token")
    x_api_key: str = Field(default="", description="X API Key")
    x_api_secret: str = Field(default="", description="X API Secret")
    x_access_token: str = Field(default="", description="X Access Token")
    x_access_token_secret: str = Field(default="", description="X Access Token Secret")

    # --- 데이터베이스 ---
    database_url: str = Field(default="sqlite:///./x_poster.db")

    # --- 앱 설정 ---
    default_language: str = Field(default="en")
    log_level: str = Field(default="INFO")

    # --- 속보 모니터 설정 ---
    monitor_enabled: bool = Field(default=True, description="뉴스 모니터 활성화")
    monitor_interval_minutes: int = Field(default=1, description="모니터 폴링 간격 (분)")
    monitor_max_alerts_per_run: int = Field(default=3, description="사이클당 최대 알림 수")
    cross_verify_min_sources: int = Field(default=4, description="속보 전송 최소 교차 출처 수")

    # --- 모닝 다이제스트 설정 ---
    digest_enabled: bool = Field(default=True, description="오전 5시 KST 모닝 다이제스트 활성화")
    digest_hour_kst: int = Field(default=5, description="다이제스트 전송 시각 (KST, 0~23)")
    digest_top_n: int = Field(default=5, description="다이제스트에 포함할 기사 수")

    # --- 콘텐츠 전략 ---
    daily_post_target: int = Field(default=30, description="하루 목표 게시 수")
    # 4 필러 비중 (비율은 float, 합계 = 1.0)
    pillar_economy_ratio: float = Field(default=0.35, description="경제/금융 필러 비중")
    pillar_crypto_ratio: float = Field(default=0.30, description="크립토/디파이 필러 비중")
    pillar_geopolitics_ratio: float = Field(default=0.20, description="지정학/정치 필러 비중")
    pillar_community_ratio: float = Field(default=0.15, description="커뮤니티 반응 필러 비중")

    # --- 안전 설정 ---
    enable_auto_post_low_risk: bool = Field(default=False)

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False

    # === 키 존재 여부 체크 ===

    def _has(self, val: str) -> bool:
        return bool(val and val.strip())

    @property
    def has_openai(self) -> bool:
        return self._has(self.openai_api_key)

    @property
    def has_anthropic(self) -> bool:
        return self._has(self.anthropic_api_key)

    @property
    def has_gemini(self) -> bool:
        return self._has(self.gemini_api_key)

    @property
    def has_grok(self) -> bool:
        return self._has(self.grok_api_key)

    @property
    def has_perplexity(self) -> bool:
        return self._has(self.perplexity_api_key)

    @property
    def has_deepseek(self) -> bool:
        return self._has(self.deepseek_api_key)

    @property
    def has_groq(self) -> bool:
        return self._has(self.groq_api_key)

    @property
    def has_tavily(self) -> bool:
        return self._has(self.tavily_api_key)

    @property
    def has_mistral(self) -> bool:
        return self._has(self.mistral_api_key)

    @property
    def has_together(self) -> bool:
        return self._has(self.together_api_key)

    @property
    def has_any_ai(self) -> bool:
        return any([
            self.has_openai, self.has_anthropic,
            self.has_gemini, self.has_grok, self.has_perplexity,
            self.has_deepseek, self.has_groq, self.has_together, self.has_mistral,
        ])

    @property
    def has_telegram_config(self) -> bool:
        return self._has(self.telegram_bot_token) and self._has(self.telegram_chat_id)

    @property
    def has_x_credentials(self) -> bool:
        return all([
            self._has(self.x_api_key), self._has(self.x_api_secret),
            self._has(self.x_access_token), self._has(self.x_access_token_secret),
        ])

    @property
    def is_full_mock_mode(self) -> bool:
        return not self.has_any_ai

    def get_effective_draft_provider(self) -> str:
        """
        실제로 사용할 드래프트 프로바이더를 결정합니다.

        - "mock"으로 명시적 설정 시 → mock 반환 (테스트/개발 모드)
        - 특정 프로바이더 설정 시 → 해당 키 보유 여부 확인 후 반환
        - 비어 있거나 알 수 없는 값 → 키 있는 첫 번째 프로바이더 자동 선택
        """
        requested = self.active_draft_provider.lower().strip()
        _draft_map = {
            "openai":    self.has_openai,
            "anthropic": self.has_anthropic,
            "deepseek":  self.has_deepseek,
            "groq":      self.has_groq,
            "together":  self.has_together,
        }
        # 명시적 mock 요청
        if requested == "mock":
            return "mock"
        # 특정 프로바이더 명시
        if requested in _draft_map and _draft_map[requested]:
            return requested
        if requested in _draft_map and not _draft_map[requested]:
            return "mock"  # 명시했지만 키 없음
        # 비어 있거나 알 수 없음 → 키 있는 첫 번째 자동 선택
        for name, has_key in _draft_map.items():
            if has_key:
                return name
        return "mock"

    def get_effective_review_provider(self) -> str:
        """실제로 사용할 리뷰어 프로바이더를 결정합니다."""
        if self.has_anthropic:
            return "anthropic"
        if self.has_mistral:
            return "mistral"
        if self.has_deepseek:
            return "deepseek"
        return "mock"

    def get_effective_research_provider(self) -> str:
        """실제로 사용할 리서치 프로바이더를 결정합니다."""
        requested = self.active_research_provider.lower().strip()
        if requested == "gemini" and self.has_gemini:
            return "gemini"
        if requested == "perplexity" and self.has_perplexity:
            return "perplexity"
        if self.has_gemini:
            return "gemini"
        if self.has_perplexity:
            return "perplexity"
        return "mock"

    def get_effective_trend_provider(self) -> str:
        """실제로 사용할 트렌드 탐지 프로바이더를 결정합니다."""
        if self.has_grok:
            return "grok"
        return "mock"

    def get_effective_factcheck_provider(self) -> str:
        """실제로 사용할 팩트체크 프로바이더를 결정합니다."""
        if self.has_perplexity:
            return "perplexity"
        return "mock"

    def get_effective_websearch_provider(self) -> str:
        """실제로 사용할 웹 검색 프로바이더를 결정합니다."""
        if self.has_tavily:
            return "tavily"
        return "mock"

    def ai_status_summary(self) -> dict[str, str]:
        """각 역할별 프로바이더 상태 요약."""
        return {
            "draft_writer":  self.get_effective_draft_provider(),
            "reviewer":      self.get_effective_review_provider(),
            "research":      self.get_effective_research_provider(),
            "trend":         self.get_effective_trend_provider(),
            "factcheck":     self.get_effective_factcheck_provider(),
            "web_search":    self.get_effective_websearch_provider(),
            "telegram":      "LIVE" if self.has_telegram_config else "MOCK",
            "x_api":         "LIVE" if self.has_x_credentials else "MOCK",
        }

    def provider_keys_status(self) -> dict[str, bool]:
        """각 프로바이더 키 존재 여부 (전체 10개)."""
        return {
            "openai":      self.has_openai,
            "anthropic":   self.has_anthropic,
            "gemini":      self.has_gemini,
            "grok":        self.has_grok,
            "perplexity":  self.has_perplexity,
            "deepseek":    self.has_deepseek,
            "groq":        self.has_groq,
            "tavily":      self.has_tavily,
            "mistral":     self.has_mistral,
            "together":    self.has_together,
        }


def validate_settings(s: Settings) -> list[str]:
    """설정값 검증. 누락 시 경고 반환."""
    warnings = []

    eff_draft = s.get_effective_draft_provider()
    eff_research = s.get_effective_research_provider()
    eff_fact = s.get_effective_factcheck_provider()

    if eff_draft == "mock":
        warnings.append(
            "[AI Draft] Mock 모드. 실제 AI 초안 생성하려면 .env에 "
            "OPENAI_API_KEY 또는 ANTHROPIC_API_KEY 설정 + "
            "ACTIVE_DRAFT_PROVIDER=openai 또는 anthropic"
        )

    if eff_research == "mock":
        warnings.append("[AI Research] Mock 모드. (v1 기본값 — 추후 확장 가능)")

    if eff_fact == "mock":
        warnings.append("[AI Factcheck] Mock 모드. (v1 기본값 — 추후 확장 가능)")

    if not s.has_telegram_config:
        warnings.append(
            "[텔레그램] 봇 토큰/채팅 ID 없음. 텔레그램 승인 불가. "
            ".env에 TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID 설정 필요."
        )

    if not s.has_x_credentials:
        warnings.append(
            "[X API] 인증정보 불완전. Mock 포스팅 모드. "
            ".env에 X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_TOKEN_SECRET 설정 필요."
        )

    return warnings


# 전역 설정 인스턴스
settings = Settings()
