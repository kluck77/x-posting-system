"""Context Package 메인 빌더 — 병렬 4개 + 직렬 2개."""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime

from app.services.context_package.category_detector import (
    detect_category,
    format_archetype,
    get_archetype_baseline,
)
from app.services.context_package.llm_clients import (
    call_gemini_korea_data,
    call_gpt_assemble,
    call_gpt_summarize,
    call_grok_x_pulse,
    call_haiku_guard,
    call_pplx_factcheck,
    extract_claims,
    fetch_polymarket_related,
)
from app.services.context_package.static_calendar import (
    KST,
    fetch_upcoming_calendar,
)

logger = logging.getLogger(__name__)


GLOBAL_HANDOFF_RULES = """[GLOBAL HANDOFF RULES — 모든 슬롯 적용]
P1. Fact > Style. Agent 4 [UNVERIFIED] 무조건 제거.
P2. Onboarding > Depth. Agent 1 풀이 누락 시 즉시 보강.
P3. Tone > Structure. Agent 2가 1차 톤 결정.
P4. Stake > Length. Agent 3 stake 부재 시 단축해서라도 삽입.
P5. Falsifiability mandatory. Agent 4 예측+반증조건 합의 단계 삭제 금지."""


CALL_COMMAND = """@HookAgent @ContextAgent @StakesAgent @PredictAgent
위 사건에 대해 4-에이전트 회의 후 통합 출력 1개.
각 에이전트 raw 노트 4개도 함께 표시."""


_VALID_CATEGORIES = {
    "crypto", "macro", "semi", "policy", "geo", "real_estate", "equity",
}


async def _empty_task() -> dict:
    return {}


async def build_context_package(
    news_text: str,
    source_meta: dict | None = None,
) -> dict | None:
    """뉴스/유튜브 분석 → Context Package dict.

    BLOCK_RECOMMENDED 시 None 반환. 각 LLM 실패는 fail-open (빈 dict).
    """
    t0 = time.time()
    source_meta = source_meta or {}

    # ── Step 1: GPT 요약 (다른 LLM 입력 의존성)
    logger.info("[CtxPkg] Step 1/4: GPT 요약 시작")
    summary = await call_gpt_summarize(news_text)
    if not summary:
        logger.error("[CtxPkg] GPT 요약 실패 — 빌드 중단")
        return None

    # 카테고리 보정
    if summary.get("category") not in _VALID_CATEGORIES:
        summary["category"] = detect_category(news_text)
    category = summary["category"]
    logger.info(
        f"[CtxPkg] 카테고리={category} severity={summary.get('severity', 0)}"
    )

    # ── Step 2: 4개 병렬 (Gemini / Perplexity / Grok / Polymarket)
    logger.info("[CtxPkg] Step 2/4: 4개 병렬 호출")
    claims = extract_claims(summary.get("summary_kr", ""))
    keywords = summary.get("primary_entities", []) or []
    needs_x = bool(summary.get("needs_x_sentiment", True))

    tasks = [
        call_gemini_korea_data(summary),
        call_pplx_factcheck(summary, claims),
        call_grok_x_pulse(summary) if needs_x else _empty_task(),
        fetch_polymarket_related(keywords),
    ]
    gemini_out, pplx_out, grok_out, pm_out = await asyncio.gather(
        *tasks, return_exceptions=True,
    )

    if isinstance(gemini_out, Exception):
        logger.warning(f"[CtxPkg] Gemini 예외: {gemini_out}")
        gemini_out = {}
    if isinstance(pplx_out, Exception):
        logger.warning(f"[CtxPkg] Perplexity 예외: {pplx_out}")
        pplx_out = {}
    if isinstance(grok_out, Exception):
        logger.warning(f"[CtxPkg] Grok 예외: {grok_out}")
        grok_out = {}
    if isinstance(pm_out, Exception):
        pm_out = {"status": "ERROR", "related": []}

    # ── Step 3: 정적 캘린더 (LLM 호출 없음)
    calendar = fetch_upcoming_calendar(category)

    # ── Step 4: Haiku 검증
    logger.info("[CtxPkg] Step 3/4: Haiku 검증")
    merged = {
        "summary":            summary,
        "korean_data":        gemini_out or {},
        "factcheck":          pplx_out or {},
        "x_pulse":            grok_out or {},
        "polymarket":         pm_out or {},
        "upcoming_calendar":  calendar,
        "category":           category,
        "archetype_baseline": get_archetype_baseline(category),
    }
    guard = await call_haiku_guard(merged)
    if guard.get("verdict") == "BLOCK_RECOMMENDED":
        logger.warning(
            f"[CtxPkg] BLOCK_RECOMMENDED: {guard.get('reasons', [])}"
        )
        return None

    merged["guard"] = guard
    merged["archetype_dna"] = (
        guard.get("recommended_archetype_dna")
        or get_archetype_baseline(category)
    )

    # ── Step 5: GPT 어셈블
    logger.info("[CtxPkg] Step 4/4: GPT 어셈블")
    pkg = await call_gpt_assemble(merged) or merged

    pkg["meta"] = {
        "build_seconds":  round(time.time() - t0, 2),
        "guard_verdict":  guard.get("verdict"),
        "build_kst":      datetime.now(KST).isoformat(),
        "category":       category,
        "draft_id":       source_meta.get("draft_id"),
    }
    logger.info(
        f"[CtxPkg] 완료: {round(time.time() - t0, 2)}초 "
        f"verdict={guard.get('verdict')}"
    )
    return pkg


def format_for_grok_heavy(pkg: dict) -> str:
    """Context Package → Grok 4.20 Heavy 투입용 텍스트."""
    if not pkg:
        return ""
    summary    = pkg.get("summary", {}) or {}
    korean     = pkg.get("korean_data", {}) or {}
    factcheck  = pkg.get("factcheck", {}) or {}
    x_pulse    = pkg.get("x_pulse", {}) or {}
    polymarket = pkg.get("polymarket", {}) or {}
    upcoming   = pkg.get("upcoming_calendar", []) or []
    archetype  = pkg.get("archetype_dna", {}) or {}

    sections = [
        GLOBAL_HANDOFF_RULES,
        "",
        "[CONTEXT_PACKAGE]",
        "",
        "사건:",
        str(summary.get("headline_kr") or ""),
        str(summary.get("summary_kr") or ""),
        "",
        f"일시: {summary.get('kst_datetime', '')}",
        "",
        f"회차 가중치: {format_archetype(archetype)}",
        "",
        "한국 시장 데이터:",
        _format_korean_data(korean),
        "",
        "검증된 사실:",
        _format_factcheck(factcheck),
        "",
        "X 여론:",
        _format_x_pulse(x_pulse),
        "",
        "Polymarket:",
        _format_polymarket(polymarket),
        "",
        "향후 일정:",
        _format_calendar(upcoming),
        "",
        "[/CONTEXT_PACKAGE]",
        "",
        CALL_COMMAND,
    ]
    return "\n".join(sections)


def _format_korean_data(data: dict) -> str:
    if not data:
        return "- 데이터 없음"
    lines = []
    fx = data.get("fx_usdkrw") or {}
    if fx and fx.get("value"):
        lines.append(
            f"- 원/달러: {fx.get('value')} ({fx.get('as_of_kst', '')})"
        )
    kp = data.get("kimchi_premium") or {}
    if kp:
        lines.append(
            f"- 김치프리미엄: BTC {kp.get('BTC')}% / "
            f"ETH {kp.get('ETH')}% / USDT {kp.get('USDT')}%"
        )
    es = data.get("exchange_share") or {}
    if es:
        lines.append(
            f"- 거래소 점유율: 업비트 {es.get('upbit')}% / "
            f"빗썸 {es.get('bithumb')}%"
        )
    if data.get("third_order_impact"):
        lines.append(f"- 3차 파급: {data['third_order_impact']}")
    return "\n".join(lines) if lines else "- 데이터 없음"


def _format_factcheck(data: dict) -> str:
    if not data:
        return "- 검증 데이터 없음"
    lines = []
    for claim in (data.get("verified_claims") or [])[:3]:
        status = "✓" if claim.get("verified") else "✗"
        lines.append(f"{status} {claim.get('claim', '')}")
    for case in (data.get("comparable_cases") or [])[:3]:
        date_ = str(case.get('date_kst', ''))[:10]
        lines.append(f"- 비교: {case.get('event', '')} ({date_})")
    return "\n".join(lines) if lines else "- 검증 데이터 없음"


def _format_x_pulse(data: dict) -> str:
    if not data:
        return "- X 데이터 없음"
    lines = []
    ks = data.get("korean_signal") or {}
    es = data.get("english_signal") or {}
    if ks:
        lines.append(
            f"- 한국어: {ks.get('sample_count', 0)}건, "
            f"{ks.get('dominant_sentiment', '')}"
        )
    if es:
        lines.append(
            f"- 영어: {es.get('sample_count', 0)}건, "
            f"{es.get('dominant_sentiment', '')}"
        )
    if data.get("emerging_narrative"):
        lines.append(f"- 신규 프레이밍: {data['emerging_narrative']}")
    return "\n".join(lines) if lines else "- X 데이터 없음"


def _format_polymarket(data: dict) -> str:
    if not data or data.get("status") != "OK":
        return "- 관련 시장 없음"
    lines = []
    for m in (data.get("related") or [])[:3]:
        lines.append(
            f"- {str(m.get('market', ''))[:60]}: "
            f"{m.get('yes_pct')}% (24h ${m.get('volume_24h', 0):,.0f})"
        )
    return "\n".join(lines) if lines else "- 관련 시장 없음"


def _format_calendar(events: list) -> str:
    if not events:
        return "- 향후 일정 없음"
    lines = []
    for e in events[:5]:
        date_ = str(e.get('date_kst', ''))[:16]
        lines.append(
            f"- {date_}: {e.get('event', '')} ({e.get('relevance', '')})"
        )
    return "\n".join(lines)
