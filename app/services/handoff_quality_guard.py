"""
handoff_quality_guard.py
========================
format_handoff() 호출 직전에 source_pack 을 검사하여 재료 품질 결함을
감지한다. 4가지 결함 타입을 독립 감지하며, 각 감지 함수는 bool 과
상세 정보를 반환한다.

설계 원칙:
- 상류 provider 코드를 수정하지 않고 출력물만 검사
- 각 감지 함수는 독립 실행 가능 (단위 테스트 용이)
- 반환은 구조화된 dict — 프롬프트에 렌더링하기 쉬운 형태
- 임계치는 모듈 상수로 선언 (Phase 1 은 하드코딩)
"""

from __future__ import annotations

import re
from typing import Literal, Optional, TypedDict

# 임계치 상수 (Phase 1 하드코딩)
ENGLISH_RATIO_THRESHOLD = 0.30
CONCEPT_TRANSLATION_MAX_LEN = 150
CONCEPT_TRANSLATION_MAX_SENTENCES = 2
MIN_CONFIRMED_FACTS = 2
HIGH_FLAG_BLOCK_THRESHOLD = 2

# 내부: confirmed_facts 에 종종 박히는 "메타 지시문" 식별용 패턴
_META_FACT_PATTERNS = (
    "확정 사실이 공급되지 않",
    "확정 사실 공급 안",
    "새 숫자",
    "고유명사 추가 금지",
    "숫자·고유명사",
    "숫자/고유명사",
    "날짜는 초안 그대로",
    "(none)",
    "n/a",
)

# 내부: 영어 비율 검사 대상 필드 목록 (source_pack 의 key)
_ENGLISH_CHECK_FIELDS = (
    "core_tension",
    "uncertainty_note",
    "interpretation_opportunity",
    "conflicts_or_uncertainty",
)

_ALPHA_RE = re.compile(r"[A-Za-z]")
_NON_WHITESPACE_SYMBOL_RE = re.compile(r"[\w가-힣]", re.UNICODE)


class QualityFlag(TypedDict):
    flag_id: str              # "angle_heuristic" | "facts_empty" 등
    severity: Literal["HIGH", "MEDIUM", "LOW"]
    description: str          # 운영자 읽을 한국어 1줄
    evidence: str             # 감지 근거 (어느 필드 어떤 값)


# ─── 유틸 ───────────────────────────────────────────────────────────────

def _english_ratio(text: str) -> float:
    """ASCII 알파벳 / (공백·구두점 제외 실제 문자 수)."""
    if not isinstance(text, str) or not text:
        return 0.0
    alpha = len(_ALPHA_RE.findall(text))
    total = len(_NON_WHITESPACE_SYMBOL_RE.findall(text))
    if total == 0:
        return 0.0
    return alpha / total


def _collect_text(value) -> str:
    """문자열 / 리스트(문자열) 모두 하나의 텍스트로 병합."""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return " ".join(str(x) for x in value if x is not None)
    if isinstance(value, dict):
        # 중첩 dict 안의 값만 텍스트 병합 (key 는 제외)
        return " ".join(_collect_text(v) for v in value.values())
    return ""


# ─── 감지 함수 4개 ─────────────────────────────────────────────────────

def detect_angle_pack_heuristic(source_pack: dict) -> Optional[QualityFlag]:
    """
    Gemini angle_pack 이 heuristic fallback 으로 생성됐는지 감지.
    """
    if not isinstance(source_pack, dict):
        return None
    ap = source_pack.get("angle_pack")
    if isinstance(ap, dict):
        # method 필드 체크
        method = ap.get("method")
        if isinstance(method, str) and "fallback" in method.lower():
            return QualityFlag(
                flag_id="angle_heuristic",
                severity="HIGH",
                description="angle_pack: Gemini heuristic fallback → 각도 설계 부재",
                evidence=f"angle_pack.method={method!r}",
            )
        # winner_angle.source 체크
        wa = ap.get("winner_angle")
        if isinstance(wa, dict):
            src = wa.get("source")
            if isinstance(src, str) and src.strip() and src.lower() != "gemini":
                return QualityFlag(
                    flag_id="angle_heuristic",
                    severity="HIGH",
                    description="angle_pack: Gemini heuristic fallback → 각도 설계 부재",
                    evidence=f"winner_angle.source={src!r}",
                )
            # winner_angle.reason 체크 (Phase 1.5a — _heuristic_angle_pack() 실 저장 위치)
            # app/services/angle_pack.py:173-177 의 빌더가 fallback 마커를
            # "reason" 필드에 박는다. 대소문자 무시, "heuristic" 또는 "fallback"
            # 둘 중 하나라도 포함되면 매치.
            reason = wa.get("reason")
            if isinstance(reason, str) and reason.strip():
                low = reason.lower()
                if ("heuristic" in low) or ("fallback" in low):
                    return QualityFlag(
                        flag_id="angle_heuristic",
                        severity="HIGH",
                        description="angle_pack: Gemini heuristic fallback → 각도 설계 부재",
                        evidence=f"angle_pack.winner_angle.reason={reason[:80]!r}",
                    )
        # edit_goal / editorial_goal 에 "heuristic fallback"
        for key in ("edit_goal", "editorial_goal"):
            v = ap.get(key)
            if isinstance(v, str) and "heuristic fallback" in v.lower():
                return QualityFlag(
                    flag_id="angle_heuristic",
                    severity="HIGH",
                    description="angle_pack: Gemini heuristic fallback → 각도 설계 부재",
                    evidence=f"angle_pack.{key}={v[:80]!r}",
                )
    # source_pack 최상위의 edit_goal 도 체크 (스키마 변형 대응)
    for key in ("edit_goal", "editorial_goal"):
        v = source_pack.get(key)
        if isinstance(v, str) and "heuristic fallback" in v.lower():
            return QualityFlag(
                flag_id="angle_heuristic",
                severity="HIGH",
                description="angle_pack: Gemini heuristic fallback → 각도 설계 부재",
                evidence=f"{key}={v[:80]!r}",
            )
    return None


def detect_confirmed_facts_empty(source_pack: dict) -> Optional[QualityFlag]:
    """
    confirmed_facts 가 비어있거나 메타 지시문만 포함되는지 감지.
    """
    if not isinstance(source_pack, dict):
        return None
    facts = source_pack.get("confirmed_facts")
    if not isinstance(facts, list):
        return QualityFlag(
            flag_id="facts_empty",
            severity="HIGH",
            description="confirmed_facts: 공급 0건 → 서사 원료 부재",
            evidence=f"type={type(facts).__name__}",
        )
    # 실질 있는 fact 만 카운트
    real_facts = 0
    for f in facts:
        if not isinstance(f, str):
            continue
        s = f.strip()
        if not s:
            continue
        low = s.lower()
        is_meta = False
        for pat in _META_FACT_PATTERNS:
            if pat.lower() in low:
                is_meta = True
                break
        if not is_meta:
            real_facts += 1
    if real_facts < MIN_CONFIRMED_FACTS:
        return QualityFlag(
            flag_id="facts_empty",
            severity="HIGH",
            description=f"confirmed_facts: 공급 {real_facts}건 → 서사 원료 부재",
            evidence=f"real_facts={real_facts} total_entries={len(facts)}",
        )
    return None


def detect_english_residue(source_pack: dict) -> Optional[QualityFlag]:
    """
    core_tension / uncertainty_note / interpretation_opportunity 필드에
    영어 잔존 (ratio > 30%) 감지.
    """
    if not isinstance(source_pack, dict):
        return None
    hits: list[tuple[str, float]] = []
    # 최상위 + angle_pack 안쪽 모두 스캔
    candidates: list[tuple[str, object]] = []
    for k in _ENGLISH_CHECK_FIELDS:
        candidates.append((k, source_pack.get(k)))
    ap = source_pack.get("angle_pack")
    if isinstance(ap, dict):
        for k in _ENGLISH_CHECK_FIELDS:
            if k in ap:
                candidates.append((f"angle_pack.{k}", ap.get(k)))
    for field_name, val in candidates:
        text = _collect_text(val)
        if not text:
            continue
        ratio = _english_ratio(text)
        if ratio > ENGLISH_RATIO_THRESHOLD:
            hits.append((field_name, ratio))
    if not hits:
        return None
    hits.sort(key=lambda x: -x[1])
    top_field, top_ratio = hits[0]
    return QualityFlag(
        flag_id="english_residue",
        severity="MEDIUM",
        description=f"영어 잔존: {top_field} 필드 영어 비율 {int(top_ratio*100)}%",
        evidence=f"fields={[h[0] for h in hits]}",
    )


def detect_concept_translation_misuse(source_pack: dict) -> Optional[QualityFlag]:
    """
    concept_translation 필드에 기사 도입부/요약이 잘못 박혔는지 감지.
    """
    if not isinstance(source_pack, dict):
        return None
    ct = source_pack.get("concept_translation")
    text = _collect_text(ct) if not isinstance(ct, str) else ct
    if not text:
        return None
    text = text.strip()
    length = len(text)
    # 문장 수 — 마침표/느낌표/물음표 기준
    sentences = [s for s in re.split(r"[\.\?!。？！]+", text) if s.strip()]
    n_sent = len(sentences)
    if length > CONCEPT_TRANSLATION_MAX_LEN or n_sent > CONCEPT_TRANSLATION_MAX_SENTENCES:
        return QualityFlag(
            flag_id="concept_translation_misuse",
            severity="MEDIUM",
            description=f"concept_translation 오용: 길이 {length}자 (정상 30~80자)",
            evidence=f"len={length} sentences={n_sent}",
        )
    return None


# ─── 집계 + 렌더 ───────────────────────────────────────────────────────

_SEVERITY_ORDER = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}


def run_quality_guard(source_pack: dict) -> dict:
    """
    4개 감지 함수 실행 후 결과 집계.
    """
    flags: list[QualityFlag] = []
    for fn in (
        detect_angle_pack_heuristic,
        detect_confirmed_facts_empty,
        detect_english_residue,
        detect_concept_translation_misuse,
    ):
        try:
            result = fn(source_pack)
        except Exception:
            result = None
        if result is not None:
            flags.append(result)
    high_count = sum(1 for f in flags if f["severity"] == "HIGH")
    medium_count = sum(1 for f in flags if f["severity"] == "MEDIUM")
    block_recommended = high_count >= HIGH_FLAG_BLOCK_THRESHOLD
    rendered = render_warning_block(flags, block_recommended)
    return {
        "flags": flags,
        "high_count": high_count,
        "medium_count": medium_count,
        "block_recommended": block_recommended,
        "rendered_warning_block": rendered,
    }


def render_warning_block(flags: list[QualityFlag], block_recommended: bool) -> str:
    """
    flags 리스트를 handoff 맨 앞에 삽입할 한국어 경고 블록으로 렌더링.
    flags 가 비어있으면 "" 리턴.
    """
    if not flags:
        return ""
    ordered = sorted(flags, key=lambda f: (_SEVERITY_ORDER.get(f["severity"], 9), f["flag_id"]))
    lines = ["## ⚠️ 재료 품질 경고 (편집 전 검토)"]
    for f in ordered:
        lines.append(f"- [{f['severity']}] {f['description']}")
    if block_recommended:
        lines.append("")
        lines.append(
            "**BLOCK_RECOMMENDED**: HIGH 2개 이상 감지. Grok Captain 은 "
            "decision=reject + operator_notes 에 \"상류 재료 부족, "
            "파이프라인 재실행 권장\" 출력할 것."
        )
    return "\n".join(lines)
