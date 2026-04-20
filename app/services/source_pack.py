"""
Source Pack
===========
Research + FactCheck + 원문 을 합친 "재료 정리" 층.

키 (10):
  confirmed_facts          — 확정 팩트 (factcheck 통과 + research key_facts)
  conflicts_or_uncertainty — 상충/미확인 (factcheck corrections + interpretation_gaps)
  korea_angle              — 한국 관점 (research context_for_foreigners 계열)
  global_angle             — 글로벌 관점 (interpretation_gaps 중 global 신호)
  watch_next               — 다음 주목 포인트 (research summary 기반)
  source_quality           — 출처 품질 메타 (url, source_type, confidence)
  historical_parallel      — 과거/현재 구조 비교 1~2문장 (Phase 1.1)
  concept_translation      — 어려운 개념 한 줄 풀이 (Phase 1.1)
  evidence_pack            — 숫자/기관명/실명/인용 후보 최대 5개 (Phase 1.1)
  closing_signal           — 마지막 문장용 강한 포인트 1개 (Phase 1.1)

구현 원칙:
- plain dict + validator 함수. Pydantic 도입 금지.
- research / factcheck 가 None 이어도 빈 값으로 채워 반환 (절대 raise 하지 않음).
- hallucination 금지 — 원문/리서치/팩트체크에 없는 내용 생성 금지.
- 호출측(orchestrator)은 이 dict 를 enriched_source / pack_context 로 변환해서
  기존 DraftWriter / Reviewer 에 주입.
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

SOURCE_PACK_KEYS: tuple[str, ...] = (
    "confirmed_facts",
    "conflicts_or_uncertainty",
    "korea_angle",
    "global_angle",
    "watch_next",
    "source_quality",
    # Phase 1.1 — structural reinforcement
    "historical_parallel",
    "concept_translation",
    "evidence_pack",
    "closing_signal",
)

# Phase 1.1 — 구조 감지 패턴 (ko + en, hallucination 금지 위해 원문 매칭만)
_HISTORICAL_HINTS = (
    "과거", "예전", "이전에는", "직전", "역사적으로", "과거와", "전례",
    "previously", "compared to", " vs ", "versus", "unlike", "as in",
)
_NUMBER_RE = re.compile(
    r"(\d+(?:\.\d+)?\s*(?:%|조|천억|억|만|배|회|건|위|퍼센트|percent|bp))"
    r"|(\$\d[\d,\.]*)"
    r"|(₩\d[\d,\.]*)"
    r"|(\d{4}년)"
    r"|(\b\d{4}\b)"
)
_QUOTE_RE = re.compile(r"[\"“”'‘’]([^\"“”'‘’]{8,160})[\"“”'‘’]")
_ORG_HINTS = (
    "NIST", "Bloomberg", "Reuters", "AP", "Fed", "BOK", "한은", "기재부", "과기부",
    "금감원", "공정위", "Binance", "Coinbase", "Upbit", "Bithumb", "삼성",
    "SK", "LG", "현대", "금융위", "한국은행", "MSIT", "국정원", "Google", "Apple",
    "Tesla", "Meta", "Microsoft", "IMF", "WTO", "UN", "OECD", "청와대", "국회",
)

_EVIDENCE_MAX = 5
_EVIDENCE_ITEM_LEN = 240

# Phase 3b — 상류 완화 정책 상수
# 상류(source_pack) 는 느슨하게, 하류(handoff_quality_guard) 는 0.30 으로 엄격.
# 2단 필터 구조. 임계치 변경은 별도 논의.
ENGLISH_RATIO_THRESHOLD_SOURCE = 0.4

_ALPHA_ONLY_RE = re.compile(r"[A-Za-z]")
_WORD_ONLY_RE = re.compile(r"[\w가-힣]")


def _english_ratio(text: str) -> float:
    """ASCII 알파벳 / (공백·구두점 제외 실제 문자) 비율.

    비교 대상 필드가 한국어인지 영어인지 판정. handoff_quality_guard 의
    동일 로직과 정렬 (임계치만 다름)."""
    if not isinstance(text, str) or not text:
        return 0.0
    alpha = len(_ALPHA_ONLY_RE.findall(text))
    total = len(_WORD_ONLY_RE.findall(text))
    return (alpha / total) if total else 0.0


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


def _split_sentences(text: str) -> list[str]:
    if not text:
        return []
    t = text.replace("?", ".").replace("!", ".")
    return [p.strip() for p in t.split(".") if p.strip()]


def _pick_historical_parallel(research) -> str:
    """research.summary / key_facts 에서 과거-현재 비교 문장을 추출."""
    if not research:
        return ""
    candidates: list[str] = []
    summary = _safe_str(getattr(research, "summary", ""), 1200)
    candidates.extend(_split_sentences(summary))
    for f in (getattr(research, "key_facts", None) or [])[:10]:
        candidates.extend(_split_sentences(str(f)))
    for s in candidates:
        low = s.lower()
        if any(h.lower() in low for h in _HISTORICAL_HINTS):
            return s[:300]
    return ""


def _pick_concept_translation(research) -> str:
    """어려운 개념의 한 줄 풀이. missing_context 라벨 팩트 우선."""
    if not research:
        return ""
    labels = getattr(research, "fact_labels", None) or {}
    for fact_text, label in labels.items():
        if label == "missing_context":
            s = _safe_str(fact_text, 240)
            if s:
                return s
    # fallback — summary 첫 문장을 한 줄 풀이로
    summary = _safe_str(getattr(research, "summary", ""), 600)
    sentences = _split_sentences(summary)
    if sentences:
        return sentences[0][:200]
    return ""


def _build_evidence_pack(research, factcheck) -> list[str]:
    """숫자/기관명/실명/quote 후보 최대 5개. 원문 문자열만 통과."""
    pool: list[str] = []
    if research:
        pool.extend(str(f) for f in (getattr(research, "key_facts", None) or []))
        summary = _safe_str(getattr(research, "summary", ""), 1200)
        pool.extend(_split_sentences(summary))
    if factcheck:
        pool.extend(_safe_list(getattr(factcheck, "corrections", None)))
        opp = _safe_str(getattr(factcheck, "interpretation_opportunity", ""), 240)
        if opp:
            pool.append(opp)

    seen: set[str] = set()
    out: list[str] = []
    for raw in pool:
        s = str(raw).strip()
        if not s or s in seen:
            continue
        has_num = bool(_NUMBER_RE.search(s))
        has_org = any(o in s for o in _ORG_HINTS)
        has_quote = bool(_QUOTE_RE.search(s))
        if not (has_num or has_org or has_quote):
            continue
        seen.add(s)
        out.append(s[:_EVIDENCE_ITEM_LEN])
        if len(out) >= _EVIDENCE_MAX:
            break
    return out


def _pick_closing_signal(
    watch_next: list[str],
    conflicts: list[str],
    research,
) -> str:
    """마지막 문장 닫기용 강한 포인트 1개."""
    for w in watch_next:
        s = str(w).strip()
        if s:
            # 내부 태그 제거 (표시용)
            s = s.replace("[marketability]", "").strip()
            if s:
                return s[:200]
    for c in conflicts:
        s = str(c).strip()
        if s.startswith("[opportunity]"):
            return s.replace("[opportunity]", "").strip()[:200]
    if research:
        summary = _safe_str(getattr(research, "summary", ""), 800)
        sentences = _split_sentences(summary)
        if sentences:
            return sentences[-1][:200]
    return ""


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
    # Phase 3b: factcheck.verified 여부와 무관하게 sources 통과.
    # verified=False 면 [unverified] 태그를 붙여 하류 Grok Captain 이
    # 신뢰도 조정 가능하게 한다 (완전 탈락 대신 태그 부여).
    confirmed: list[str] = []
    if factcheck:
        fc_verified = bool(getattr(factcheck, "verified", False))
        fc_sources = _safe_list(getattr(factcheck, "sources", None))
        for s in fc_sources:
            if fc_verified:
                confirmed.append(s)
            else:
                confirmed.append(f"[unverified] {s}")
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

    # Phase 3b 최종 방어선: 위 두 경로 모두 비었고 research.summary 가 있으면
    # summary 자체를 confirmed[0] 으로 fallback. 영어 비율 > 0.4 면 [en] 프리픽스.
    if not confirmed and research:
        fallback_summary = _safe_str(getattr(research, "summary", ""), 300)
        if fallback_summary:
            if _english_ratio(fallback_summary) > ENGLISH_RATIO_THRESHOLD_SOURCE:
                confirmed.append(f"[en] {fallback_summary}")
            else:
                confirmed.append(fallback_summary)

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
            # Phase 3b: 영어 비율 > 0.4 면 [en] 프리픽스. 자동 번역은 하지 않는다.
            # 하류 handoff_quality_guard 의 english_residue 감지(임계 0.3)가 발동하도록.
            if _english_ratio(summary) > ENGLISH_RATIO_THRESHOLD_SOURCE:
                korea_angle.append(f"[en] {summary}")
            else:
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
            parts = _split_sentences(summary)
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

    # --- Phase 1.1 구조 필드 ---
    historical_parallel = _pick_historical_parallel(research)
    concept_translation = _pick_concept_translation(research)
    evidence_pack       = _build_evidence_pack(research, factcheck)
    closing_signal      = _pick_closing_signal(watch_next[:3], conflicts[:6], research)

    pack: dict = {
        "confirmed_facts":          confirmed[:12],
        "conflicts_or_uncertainty": conflicts[:10],
        "korea_angle":              korea_angle[:6],
        "global_angle":             global_angle[:6],
        "watch_next":               watch_next[:6],
        "source_quality":           source_quality,
        "historical_parallel":      historical_parallel,
        "concept_translation":      concept_translation,
        "evidence_pack":            evidence_pack,
        "closing_signal":           closing_signal,
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
                     "korea_angle", "global_angle", "watch_next",
                     "evidence_pack"):
        if not isinstance(pack[list_key], list):
            raise ValueError(f"source_pack.{list_key} must be list")
    if not isinstance(pack["source_quality"], dict):
        raise ValueError("source_pack.source_quality must be dict")
    # Phase 1.1 string fields
    for str_key in ("historical_parallel", "concept_translation", "closing_signal"):
        if not isinstance(pack[str_key], str):
            raise ValueError(f"source_pack.{str_key} must be str")
    # evidence_pack item-level
    if len(pack["evidence_pack"]) > _EVIDENCE_MAX:
        raise ValueError(
            f"source_pack.evidence_pack exceeds cap {_EVIDENCE_MAX}: "
            f"{len(pack['evidence_pack'])}"
        )
    for item in pack["evidence_pack"]:
        if not isinstance(item, str):
            raise ValueError("source_pack.evidence_pack items must be str")
        if len(item) > _EVIDENCE_ITEM_LEN:
            raise ValueError(
                f"source_pack.evidence_pack item exceeds {_EVIDENCE_ITEM_LEN}: {len(item)}"
            )
