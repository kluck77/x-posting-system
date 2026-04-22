"""
설정 관리 모듈
=============
.env 파일에서 환경변수를 읽어오고, 앱 전체에서 사용할 설정값을 관리합니다.

5-역할 AI 아키텍처:
  - ChatGPT (OpenAI): 드래프트 작성 (빠른 초안, 톤 조정)
  - Claude (Anthropic): 리뷰어 (리스크 판단, 최종 다듬기)
  - Gemini (Google): 리서치 & 분석
  - Grok (xAI): 트렌드 탐지
  - Perplexity: 팩트체크 & 출처
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
    openai_api_key: str = Field(default="", description="OpenAI API 키 (Draft Writer)")
    anthropic_api_key: str = Field(default="", description="Anthropic Claude (Reviewer + Draft)")
    gemini_api_key: str = Field(default="", description="Google Gemini (Researcher)")
    grok_api_key: str = Field(default="", description="xAI Grok (TrendHunter) — x.ai 에서 발급")
    perplexity_api_key: str = Field(default="", description="Perplexity (FactChecker)")

    # --- Naver Open API (뉴스 검색, 무료) ---
    naver_client_id: str = Field(default="", description="Naver API Client ID (뉴스 검색)")
    naver_client_secret: str = Field(default="", description="Naver API Client Secret")

    # --- Crypto Intel Sources (수집 단계 AI 미사용, 키 없으면 adapter 비활성) ---
    open_dart_api_key: str = Field(default="", description="Open DART (한국 전자공시)")
    congress_api_key: str = Field(default="", description="US Congress API (법안)")
    finnhub_api_key: str = Field(default="", description="Finnhub (마켓/기업 뉴스)")
    cryptopanic_api_key: str = Field(default="", description="CryptoPanic (크립토 뉴스 스트림)")
    newsapi_api_key: str = Field(default="", description="NewsAPI — Phase 2 옵션, 현재 stub")
    coingecko_api_key: str = Field(default="", description="CoinGecko — Phase 2 옵션, 현재 stub")

    # --- 활성 프로바이더 선택 ---
    active_draft_provider: str = Field(default="mock", description="초안 작성 프로바이더")
    active_research_provider: str = Field(default="mock", description="리서치 프로바이더")
    active_trend_provider: str = Field(default="mock", description="트렌드 탐지 프로바이더")
    active_factcheck_provider: str = Field(default="mock", description="팩트체크 프로바이더")

    # --- 텔레그램 ---
    telegram_bot_token: str = Field(default="", description="텔레그램 봇 토큰")
    telegram_chat_id: str = Field(default="", description="텔레그램 채팅 ID")

    # --- X (트위터) --- 자동 게시 제거됨, 수동 게시 전용
    x_username: str = Field(default="sskorea02", description="X 계정 사용자명 (@ 없이, 답글 모니터에서 사용)")

    # --- 데이터베이스 ---
    database_url: str = Field(default="sqlite:///./x_poster.db")

    # --- 앱 설정 ---
    default_language: str = Field(default="ko")
    log_level: str = Field(default="INFO")

    # --- 속보 모니터 설정 ---
    monitor_enabled: bool = Field(default=True, description="뉴스 모니터 활성화")
    monitor_interval_minutes: int = Field(default=1, description="모니터 폴링 간격 (분)")
    monitor_max_alerts_per_run: int = Field(default=3, description="사이클당 최대 알림 수")
    cross_verify_min_sources: int = Field(default=4, description="속보 전송 최소 교차 출처 수")
    alert_score_threshold: int = Field(default=45, description="후보알림 전송 최소 점수 (0~100, 24h 로그로 튜닝)")
    alert_near_miss_window: int = Field(default=10, description="near-miss 로그 창 (threshold 바로 아래 N점)")

    # --- 모닝 다이제스트 설정 ---
    digest_enabled: bool = Field(default=True, description="오전 5시 KST 모닝 다이제스트 활성화")
    digest_hour_kst: int = Field(default=5, description="다이제스트 전송 시각 (KST, 0~23)")
    digest_top_n: int = Field(default=5, description="다이제스트에 포함할 기사 수")

    # --- 콘텐츠 전략 ---
    daily_post_target: int = Field(default=30, description="하루 목표 게시 수")

    # --- 일일 사용량 제한 ---
    max_drafts_per_day: int = Field(default=5, description="하루 최대 AI 초안 생성 수")
    max_telegram_per_day: int = Field(default=5, description="하루 최대 텔레그램 승인 카드 수")
    max_posts_per_day: int = Field(default=10, description="하루 최대 X 게시 수")
    # 4 필러 비중 (비율은 float, 합계 = 1.0)
    pillar_economy_ratio: float = Field(default=0.35, description="경제/금융 필러 비중")
    pillar_crypto_ratio: float = Field(default=0.30, description="크립토/디파이 필러 비중")
    pillar_geopolitics_ratio: float = Field(default=0.20, description="지정학/정치 필러 비중")
    pillar_community_ratio: float = Field(default=0.15, description="커뮤니티 반응 필러 비중")

    # --- 안전 설정 ---
    enable_auto_post_low_risk: bool = Field(default=False)

    # --- Pack Chain (Grok Handoff) --- Phase 1: off by default
    pack_chain_enabled: bool = Field(
        default=False,
        description="Pack chain 경로 활성화 (source_pack + angle_pack + sidecar). "
                    "실패 시 legacy 경로로 fallback.",
    )

    # --- Stibee 뉴스레터 (email_sender/stibee_sender.py 가 사용) ---
    stibee_api_key: str = Field(default="", description="Stibee AccessToken")
    stibee_list_id: str = Field(default="", description="Stibee 리스트 ID")
    stibee_sender_email: str = Field(default="", description="발신자 이메일")

    # --- UTM (email_sender/url_builder.py 가 사용) ---
    utm_source_default: str = Field(default="sskorea02")
    utm_medium_newsletter: str = Field(default="email")
    utm_campaign_default: str = Field(default="brief")

    # --- Affiliate (affiliate_registry.py 가 사용) ---
    affiliate_enabled: bool = Field(default=False, description="Affiliate 링크 삽입 킬스위치")
    affiliate_links_path: str = Field(default="data/affiliate_links.json")

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

    # ── Crypto Intel Sources ────────────────────────────────────────────────

    @property
    def has_open_dart(self) -> bool:
        return self._has(self.open_dart_api_key)

    @property
    def has_congress(self) -> bool:
        return self._has(self.congress_api_key)

    @property
    def has_finnhub(self) -> bool:
        return self._has(self.finnhub_api_key)

    @property
    def has_cryptopanic(self) -> bool:
        return self._has(self.cryptopanic_api_key)

    @property
    def has_newsapi(self) -> bool:
        return self._has(self.newsapi_api_key)

    @property
    def has_coingecko(self) -> bool:
        return self._has(self.coingecko_api_key)

    def intel_sources_status(self) -> dict[str, bool]:
        """Crypto Intel adapter 별 키 보유 여부 (True=enabled 가능)."""
        return {
            "open_dart":   self.has_open_dart,
            "congress":    self.has_congress,
            "finnhub":     self.has_finnhub,
            "cryptopanic": self.has_cryptopanic,
            "newsapi":     self.has_newsapi,
            "coingecko":   self.has_coingecko,
        }

    @property
    def has_any_ai(self) -> bool:
        return any([
            self.has_openai, self.has_anthropic,
            self.has_gemini, self.has_grok, self.has_perplexity,
        ])

    @property
    def has_telegram_config(self) -> bool:
        return self._has(self.telegram_bot_token) and self._has(self.telegram_chat_id)

    @property
    def has_x_credentials(self) -> bool:
        """자동 게시 제거됨 — 항상 False."""
        return False

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

    def ai_status_summary(self) -> dict[str, str]:
        """각 역할별 프로바이더 상태 요약."""
        return {
            "draft_writer":  self.get_effective_draft_provider(),
            "reviewer":      self.get_effective_review_provider(),
            "research":      self.get_effective_research_provider(),
            "trend":         self.get_effective_trend_provider(),
            "factcheck":     self.get_effective_factcheck_provider(),
            "telegram":      "LIVE" if self.has_telegram_config else "MOCK",
            "x_api":         "MANUAL (자동 게시 제거됨)",
        }

    def provider_keys_status(self) -> dict[str, bool]:
        """각 프로바이더 키 존재 여부."""
        return {
            "openai":      self.has_openai,
            "anthropic":   self.has_anthropic,
            "gemini":      self.has_gemini,
            "grok":        self.has_grok,
            "perplexity":  self.has_perplexity,
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

    # X 자동 게시 제거됨 — 수동 게시 전용

    if not any(s.intel_sources_status().values()):
        warnings.append(
            "[Crypto Intel] 모든 수집 키 비어있음 (open_dart/congress/"
            "finnhub/cryptopanic). 대시보드 탭은 렌더되지만 수집 결과는 0 건."
        )

    return warnings


# 전역 설정 인스턴스
settings = Settings()
