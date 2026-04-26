"""API 비용 모니터링 — 월간 한도 80% 도달 경고.

기존 api_cost_tracker (in-memory) 와 별도로 sqlite api_costs 테이블에
영속 기록. record_usage 가 fail-open 으로 log_api_call 도 호출.
"""
from __future__ import annotations

import logging
import re
import sqlite3
import time
from datetime import datetime

from app.config import settings

logger = logging.getLogger(__name__)


def _sqlite_path() -> str:
    url = settings.database_url or ""
    m = re.match(r"sqlite:///(.+)", url)
    return m.group(1) if m else "./x_poster.db"


# 모델별 토큰당 비용 (USD per 1M tokens)
COST_TABLE: dict[str, dict[str, float]] = {
    # OpenAI
    "gpt-4o":          {"input": 2.50, "output": 10.0},
    "gpt-4o-mini":     {"input": 0.15, "output": 0.60},
    # Anthropic
    "claude-haiku-4-5":          {"input": 0.80, "output": 4.0},
    "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.0},
    "claude-sonnet-4-6":         {"input": 3.00, "output": 15.0},
    "claude-opus-4-7":           {"input": 15.0, "output": 75.0},
    # Gemini
    "gemini-2.5-flash":   {"input": 0.30, "output": 2.50},
    # Perplexity (sonar 근사치)
    "sonar":              {"input": 1.0,  "output": 1.0},
    "perplexity-sonar":   {"input": 1.0,  "output": 1.0},
    # xAI Grok
    "grok-2":             {"input": 2.0,  "output": 10.0},
    "grok-2-latest":      {"input": 2.0,  "output": 10.0},
    "grok-3-mini-fast":   {"input": 0.30, "output": 0.50},
}

# 월 한도 (USD)
MONTHLY_LIMITS: dict[str, float] = {
    "openai":     20.0,
    "anthropic":  30.0,
    "gemini":     30.0,
    "perplexity": 20.0,
    "grok":       30.0,
}

_PROVIDER_ORDER = ["openai", "anthropic", "gemini", "perplexity", "grok"]


def _ensure_table(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS api_costs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            provider TEXT,
            model TEXT,
            input_tokens INTEGER,
            output_tokens INTEGER,
            cost_usd REAL,
            called_at REAL
        )
    """)


def _lookup_cost(model: str) -> dict[str, float]:
    """모델명에서 가격표 조회. 정확 일치 우선, 부분 매치 fallback."""
    if model in COST_TABLE:
        return COST_TABLE[model]
    low = (model or "").lower()
    for key, info in COST_TABLE.items():
        if key.lower() in low or low in key.lower():
            return info
    return {"input": 0.0, "output": 0.0}


def log_api_call(
    provider: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
) -> None:
    """API 호출 1건 비용 기록. 실패해도 fail-open."""
    try:
        cost_info = _lookup_cost(model)
        cost = (
            (input_tokens or 0) / 1_000_000 * cost_info["input"]
            + (output_tokens or 0) / 1_000_000 * cost_info["output"]
        )
        conn = sqlite3.connect(_sqlite_path())
        _ensure_table(conn)
        conn.execute("""
            INSERT INTO api_costs
            (provider, model, input_tokens, output_tokens, cost_usd, called_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            provider, model, int(input_tokens or 0), int(output_tokens or 0),
            cost, time.time(),
        ))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.debug(f"[CostMonitor] log 실패 (무시): {e}")


def get_monthly_usage() -> dict[str, float]:
    """이번 달 누적 비용 by provider."""
    usage: dict[str, float] = {p: 0.0 for p in MONTHLY_LIMITS}
    try:
        month_start = datetime.now().replace(
            day=1, hour=0, minute=0, second=0, microsecond=0,
        ).timestamp()
        conn = sqlite3.connect(_sqlite_path())
        _ensure_table(conn)
        cur = conn.execute("""
            SELECT provider, COALESCE(SUM(cost_usd), 0)
            FROM api_costs
            WHERE called_at >= ?
            GROUP BY provider
        """, (month_start,))
        for provider, total in cur.fetchall():
            if provider in usage:
                usage[provider] = round(float(total or 0), 4)
        conn.close()
    except Exception as e:
        logger.warning(f"[CostMonitor] 월간 집계 실패: {e}")
    return usage


def check_limits() -> list[str]:
    """80% 도달/초과 경고."""
    usage = get_monthly_usage()
    warnings: list[str] = []
    for provider, used in usage.items():
        limit = MONTHLY_LIMITS.get(provider, 0)
        if limit <= 0:
            continue
        ratio = used / limit
        if ratio >= 1.0:
            warnings.append(
                f"❌ {provider} 한도 초과: ${used:.2f} / ${limit:.0f}"
            )
        elif ratio >= 0.8:
            warnings.append(
                f"⚠️ {provider} 80% 도달: "
                f"${used:.2f} / ${limit:.0f} ({ratio*100:.0f}%)"
            )
    return warnings


def format_cost_report() -> str:
    """텔레그램 비용 리포트 (월간 한도 대비 진행률 막대)."""
    usage = get_monthly_usage()
    lines = ["💰 이번 달 API 비용", ""]
    total = 0.0
    for provider in _PROVIDER_ORDER:
        used = usage.get(provider, 0.0)
        limit = MONTHLY_LIMITS.get(provider, 0)
        ratio_pct = (used / limit * 100) if limit > 0 else 0.0
        bar_filled = max(0, min(10, int(ratio_pct / 10)))
        bar = "█" * bar_filled + "░" * (10 - bar_filled)
        lines.append(
            f"{provider:11s} ${used:6.2f} / ${limit:.0f}  "
            f"[{bar}] {ratio_pct:.0f}%"
        )
        total += used
    lines.append("")
    lines.append(f"합계: ${total:.2f}")
    return "\n".join(lines)
