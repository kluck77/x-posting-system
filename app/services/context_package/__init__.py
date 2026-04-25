"""Context Package 자동 생성 모듈.

뉴스/유튜브 분석 결과 → Grok 4.20 Heavy 4-agent 투입용 패키지.

병렬 4개 (Gemini Search / Perplexity Sonar / Grok firehose / Polymarket)
+ 직렬 2개 (GPT 요약 → Haiku 검증 → GPT 어셈블).

자동 포스팅 없음. 운영자가 Grok Heavy 에 수동 복붙 후 발행.
"""

from app.services.context_package.builder import (
    build_context_package,
    format_for_grok_heavy,
)

__all__ = ["build_context_package", "format_for_grok_heavy"]
