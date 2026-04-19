"""
Source Pack
===========
Research + FactCheck + 원문 을 합친 "재료 정리" 층.

키 (6):
  confirmed_facts          — 확정 팩트 (factcheck 통과 + research key_facts)
  conflicts_or_uncertainty — 상충/미확인 (factcheck corrections + interpretation_gaps)
  korea_angle              — 한국 관점 (research context_for_foreigners 계열)
  global_angle             — 글로벌 관점 (interpretation_gaps 중 global 신호)
  watch_next               — 다음 주목 포인트 (research summary 기반)
  source_quality           — 출처 품질 메타 (url, source_type, confidence)

구현 원칙:
- plain dict + validator 함수. Pydantic 도입 금지.
- research / factcheck 가 None 이어도 빈 값으로 채워 반환 (절대 raise 하지 않음).
- 호출측(orchestrator)은 이 dict 를 enriched_source / pack_context 로 변환해서
  기존 DraftWriter / Reviewer 에 주입.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

SOURCE_PACK_KEYS: tuple[str, ...] = (
    "confirmed_facts",
    "conflicts_or_uncertainty",
    "korea_angle",
    "global_angle",
    "watch_next",
    "source_quality",
)


def _safe_list(x: Any) -> list[str]:
    if not x:
        return []
    if isinstance(x, list):
        return [str(v).strip() for v in x if v]
    if isinstance(x, str):
        s = x.strip()
        return [s] if s else []
    return []


def _safe_str(x: Any, limit: int = 500) -> str:
    if not x:
        return ""
    s = str(x).strip()
    return s[:limit]


def build_source_pack(
    source_item,
    input_data,
    research=None,
    factcheck=None,
) -> dict:
    """
    재료 정리 dict 생성.

    Args:
        source_item: app.models.content.SourceItem (DB 객체)
        input_data:  app.models.content.SourceItemCreate (schema)
        research:    app.providers.base.ResearchResult | None
        factcheck:   app.providers.base.FactCheckResult | None

    실패를 raise 하지 않는다. 누락된 입력은 빈 값으로 채운다.
    """
    # --- confirmed_facts ---
    confirmed: list[str] = []
    if factcheck and getattr(factcheck, "verified", False):
        confirmed.extend(_safe_list(getattr(factcheck, "sources", None)))
    if research and getattr(research, "key_facts", None):
        # research.fact_labels 에서 confirms_common_narrative 또는 challenges_assumption 으로
        # 태깅된 팩트를 우선 confirmed 로 간주 (둘 다 "실재" 팩트).
        labels = getattr(research, "fact_labels", None) or {}
        for fact in research.key_facts[:10]:
            fact_s = str(fact).strip()
            if not fact_s:
                continue
            label = labels.get(fact_s, "")
            if label in ("confirms_common_narrative", "challenges_assumption"):
                confirmed.append(f"{fact_s} [{label}]")
            else:
                confirmed.append(fact_s)

    # --- conflicts_or_uncertainty ---
    conflicts: list[str] = []
    if factcheck:
        conflicts.extend(_safe_list(getattr(factcheck, "corrections", None)))
        opp = _safe_str(getattr(factcheck, "interpretation_opportunity", ""), 200)
        if opp:
            conflicts.append(f"[opportunity] {opp}")
    if research and getattr(research, "interpretation_gaps", None):
        for gap in research.interpretation_gaps[:5]:
            gap_s = str(gap).strip()
            if gap_s:
                conflicts.append(f"[gap] {gap_s}")

    # --- korea_angle / global_angle ---
    korea_angle: list[str] = []
    global_angle: list[str] = []
    if research:
        # research 객체엔 context_for_foreigners 필드가 없으므로 summary 에서 추출.
        # (ResearchResult 는 summary, sources, interpretation_gaps 만 갖고 있다)
        summary = _safe_str(getattr(research, "summary", ""), 800)
        if summary:
            korea_angle.append(summary)
        # interpretation_gaps 중 "Reuters/Bloomberg/global/foreign" 키워드가 있으면 global_angle 로.
        gaps = getattr(research, "interpretation_gaps", None) or []
        for gap in gaps[:6]:
            gap_s = str(gap).strip()
            if not gap_s:
                continue
            low = gap_s.lower()
            if any(k in low for k in ("reuters", "bloomberg", "global", "foreign",
                                       "english", "international", "world")):
                global_angle.append(gap_s)

    # --- watch_next ---
    watch_next: list[str] = []
    # factcheck 의 marketability_signal 이 있으면 watch_next 에 반영
    if factcheck:
        mkt = _safe_str(getattr(factcheck, "marketability_signal", ""), 200)
        if mkt:
            watch_next.append(f"[marketability] {mkt}")
    # research.summary 의 마지막 문장 하나를 "다음 주목" 시그널로 사용 (휴리스틱)
    if research:
        summary = _safe_str(getattr(research, "summary", ""), 800)
        if summary:
            # 문장 분리 단순 휴리스틱 — 마침표 기반
            parts = [p.strip() for p in summary.replace("?", ".").replace("!", ".").split(".") if p.strip()]
            if parts:
                watch_next.append(parts[-1][:200])

    # --- source_quality ---
    source_type = getattr(input_data, "source_type", None) or getattr(source_item, "source_type", None) or "manual"
    url = getattr(input_data, "url", None) or getattr(source_item, "url", None) or ""
    title = getattr(input_data, "title", None) or getattr(source_item, "title", None) or ""
    confidence = "low"
    if factcheck:
        confidence = _safe_str(getattr(factcheck, "confidence", "low"), 20) or "low"
    source_quality = {
        "title": title[:300],
        "url": url[:500],
        "source_type": source_type,
        "factcheck_confidence": confidence,
        "factcheck_verified": bool(getattr(factcheck, "verified", False)) if factcheck else False,
    }

    pack: dict = {
        "confirmed_facts":          confirmed[:12],
        "conflicts_or_uncertainty": conflicts[:10],
        "korea_angle":              korea_angle[:6],
        "global_angle":             global_angle[:6],
        "watch_next":               watch_next[:6],
        "source_quality":           source_quality,
    }

    try:
        validate_source_pack(pack)
    except Exception as e:
        # validator 실패는 로깅만 (호출측이 try/except 로 감싸고 있으므로 raise 해도 legacy fallback)
        logger.warning(f"[source_pack] validate failed: {e}")
        raise

    return pack


def validate_source_pack(pack: dict) -> None:
    """필수 키 + 타입 체크. 불일치 시 ValueError."""
    if not isinstance(pack, dict):
        raise ValueError("source_pack must be dict")
    for k in SOURCE_PACK_KEYS:
        if k not in pack:
            raise ValueError(f"source_pack missing key: {k}")
    for list_key in ("confirmed_facts", "conflicts_or_uncertainty",
                     "korea_angle", "global_angle", "watch_next"):
        if not isinstance(pack[list_key], list):
            raise ValueError(f"source_pack.{list_key} must be list")
    if not isinstance(pack["source_quality"], dict):
        raise ValueError("source_pack.source_quality must be dict")
