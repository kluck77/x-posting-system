"""
API 비용 추적기
================
각 AI provider 호출의 토큰 사용량과 예상 비용을 추적합니다.
인메모리 카운터 (서버 재시작 시 리셋).

사용법:
  from app.services.api_cost_tracker import record_usage, get_usage_summary

  record_usage("openai", "gpt-4o-mini", "DraftWriter", input_tokens=350, output_tokens=200)
  summary = get_usage_summary()  # 텔레그램에 표시할 텍스트
"""

import logging
import threading
from collections import defaultdict
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

_KST = timezone(timedelta(hours=9))
_lock = threading.Lock()

# {date_str: {provider: {calls, input_tokens, output_tokens}}}
_daily: dict[str, dict[str, dict]] = defaultdict(
    lambda: defaultdict(lambda: {"calls": 0, "input_tokens": 0, "output_tokens": 0})
)

# 마지막 서버 시작 시각
_started_at: str = datetime.now(tz=_KST).strftime("%Y-%m-%d %H:%M")

# ── 토큰당 예상 비용 (USD, 1M 토큰 기준 → 1토큰 단가) ──
# NOTE: 공식 가격표 변경 시 여기만 수정하면 됨
# confidence: medium — 실제 과금 구조와 다를 수 있음
_PRICING: dict[str, dict[str, float]] = {
    "openai": {"input": 0.15 / 1_000_000, "output": 0.60 / 1_000_000},      # gpt-4o-mini
    "anthropic": {"input": 3.00 / 1_000_000, "output": 15.00 / 1_000_000},   # claude-sonnet-4
    "anthropic-haiku": {"input": 0.80 / 1_000_000, "output": 4.00 / 1_000_000},  # claude-haiku-4.5
    "gemini": {"input": 0.15 / 1_000_000, "output": 0.60 / 1_000_000},       # gemini-2.5-flash (유료 tier)
    "grok": {"input": 0.30 / 1_000_000, "output": 0.50 / 1_000_000},         # grok-3-mini-fast
    "perplexity": {"input": 1.00 / 1_000_000, "output": 1.00 / 1_000_000},   # sonar (근사치)
}


def _today() -> str:
    return datetime.now(tz=_KST).strftime("%Y-%m-%d")


def _pricing_key(provider: str, model: str) -> str:
    """provider+model에 맞는 가격표 키를 반환."""
    if provider == "anthropic" and "haiku" in model.lower():
        return "anthropic-haiku"
    return provider


def record_usage(
    provider: str,
    model: str,
    caller: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
) -> None:
    """API 호출 1건을 기록한다."""
    key = _today()
    with _lock:
        bucket = _daily[key][provider]
        bucket["calls"] += 1
        bucket["input_tokens"] += input_tokens
        bucket["output_tokens"] += output_tokens
    logger.debug(
        f"[CostTracker] {provider}/{model} caller={caller} "
        f"+{input_tokens}in +{output_tokens}out"
    )


def get_usage_summary() -> str:
    """오늘 + 최근 7일 사용량 요약 텍스트 (텔레그램 HTML용)."""
    today = _today()

    lines = [
        f"💰 <b>AI API 사용량</b>",
        f"<i>추적 시작: {_started_at} KST</i>\n",
    ]

    # ── 오늘 ──
    lines.append(f"📅 <b>오늘 ({today})</b>")
    today_total_cost = 0.0

    with _lock:
        today_data = dict(_daily.get(today, {}))

    if not today_data:
        lines.append("  (호출 없음)")
    else:
        for provider in sorted(today_data.keys()):
            d = today_data[provider]
            calls = d["calls"]
            in_tok = d["input_tokens"]
            out_tok = d["output_tokens"]

            # 비용 추정
            pk = _pricing_key(provider, "")
            pricing = _PRICING.get(pk, _PRICING.get(provider, {"input": 0, "output": 0}))
            cost = in_tok * pricing["input"] + out_tok * pricing["output"]
            today_total_cost += cost

            icon = _provider_icon(provider)
            lines.append(
                f"  {icon} <b>{provider}</b>: {calls}회 | "
                f"in {_fmt_tokens(in_tok)} out {_fmt_tokens(out_tok)} | "
                f"~${cost:.4f}"
            )

    lines.append(f"\n  <b>오늘 예상 합계: ~${today_total_cost:.4f}</b>")

    # ── 최근 7일 합산 ──
    lines.append(f"\n📊 <b>최근 7일 합산</b>")
    week_totals: dict[str, dict] = defaultdict(
        lambda: {"calls": 0, "input_tokens": 0, "output_tokens": 0}
    )
    week_total_cost = 0.0

    with _lock:
        for date_str, providers in _daily.items():
            for provider, d in providers.items():
                w = week_totals[provider]
                w["calls"] += d["calls"]
                w["input_tokens"] += d["input_tokens"]
                w["output_tokens"] += d["output_tokens"]

    if not week_totals:
        lines.append("  (데이터 없음)")
    else:
        for provider in sorted(week_totals.keys()):
            d = week_totals[provider]
            pk = _pricing_key(provider, "")
            pricing = _PRICING.get(pk, {"input": 0, "output": 0})
            cost = d["input_tokens"] * pricing["input"] + d["output_tokens"] * pricing["output"]
            week_total_cost += cost

            icon = _provider_icon(provider)
            lines.append(
                f"  {icon} <b>{provider}</b>: {d['calls']}회 | "
                f"~${cost:.4f}"
            )

        lines.append(f"\n  <b>누적 예상 합계: ~${week_total_cost:.4f}</b>")

    lines.append(
        f"\n<i>⚠️ 비용은 추정치입니다 (confidence: medium).\n"
        f"실제 과금은 각 provider 콘솔에서 확인하세요.</i>"
    )

    return "\n".join(lines)


def _fmt_tokens(n: int) -> str:
    """토큰 수를 읽기 좋게 포맷."""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


def _provider_icon(provider: str) -> str:
    icons = {
        "openai": "🟢",
        "anthropic": "🟣",
        "gemini": "🔵",
        "grok": "⚫",
        "perplexity": "🟠",
    }
    return icons.get(provider, "⬜")
