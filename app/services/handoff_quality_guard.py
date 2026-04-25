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
    4개 감지 함수 실행 + Phase 2 judge() 병합.

    judge() 가 REJECT 또는 REWRITE_REQUIRED 판정 시 block_recommended 도
    True 로 강제 — 기존 _BLOCK_RECOMMENDED_CACHE 게이트와 자연 연동.
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

    # Phase 2 — judge() 병합 (final_body 없이도 source/angle 기반 평가 가능)
    verdict: QualityVerdict | None = None
    try:
        verdict = judge_for_pack(
            source_pack=source_pack,
            angle_pack=source_pack.get("angle_pack"),
            final_body=str(source_pack.get("final_body") or ""),
            editorial_meta=source_pack.get("editorial_meta"),
        )
        # 좁힌 정의: '안전 위반' verdict (REJECT) 일 때만 block.
        # 기존 grade=='REJECT' 라도 안전 위반 아니면 카드 송출 (운영자 판단).
        if verdict.verdict == "REJECT":
            block_recommended = True
    except Exception as _je:
        _judge_logger.warning(f"[run_quality_guard] judge 실패 (무시): {_je}")

    rendered = render_warning_block(flags, block_recommended)
    out = {
        "flags": flags,
        "high_count": high_count,
        "medium_count": medium_count,
        "block_recommended": block_recommended,
        "rendered_warning_block": rendered,
    }
    if verdict is not None:
        out["verdict"] = {
            "decision":     verdict.decision,
            "grade":        verdict.grade,
            "score":        verdict.score,
            "reasons":      verdict.reasons,
            "warnings":     verdict.warnings,
            "block_reason": verdict.block_reason,
            "verdict":      verdict.verdict,
        }
    return out


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


# =====================================================================
# Phase 2 — judge() 시스템 (draft_1465 유형 차단)
#
# 기존 run_quality_guard 는 source_pack 4 결함만 검사한다. judge() 는
# 본문 + angle + key_evidence 까지 보고 APPROVE/REWRITE_REQUIRED/REJECT
# 자동 판정한다. orchestrator 의 _BLOCK_RECOMMENDED_CACHE 와 자연스럽게
# 연결되도록 run_quality_guard 가 내부에서 judge() 도 호출해 결과를
# 병합한다.
# =====================================================================

import logging as _logging
from dataclasses import dataclass, field as _field

_judge_logger = _logging.getLogger(__name__)


# ─── 오염 패턴 ───────────────────────────────────────────────────────
CAUSAL_OVERREACH = re.compile(
    r"왜곡한다|조종한다|악순환|숨겨진\s*불안"
    r"|필연적으로|반드시\s*온다|폭락할\s*것"
    r"|붕괴\s*임박|무조건|절대적으로",
    re.IGNORECASE,
)

EXTERNAL_COMPARISON = re.compile(
    r"일본\s*비교|플라자합의|잃어버린\s*\d+년"
    r"|중국\s*vs\s*한국|미국\s*vs\s*한국",
    re.IGNORECASE,
)

TEMPLATE_CONTAMINATION = re.compile(
    r"유튜브\s*영상\s*분석\s*모드"
    r"|Uncertainty\s+on\s+record"
    r"|HOME\s+종합\s+경제\s+가\s+가"
    r"|\[\s*\d{1,2}:\d{2}(?::\d{2})?\s*\]"   # 타임스탬프 잔재
    r"|(?:^|\n)\s*\d{1,2}:\d{2}(?::\d{2})?\s+[가-힣]"
    r"|\[SYSTEM\]|\[DEBUG\]"
    r"|analysis\.mode|debug\.text",
    re.IGNORECASE,
)

DUPLICATE_KEYS = [
    "진짜 쟁점",
    "지금 봐야 할 포인트",
    "훅 후보",
    "반드시 살릴",
    "살릴 가치",
]


# ─── 판정 결과 ───────────────────────────────────────────────────────
@dataclass
class QualityVerdict:
    decision:     str                              # APPROVE / REWRITE_REQUIRED / REJECT
    grade:        str                              # A / B / C / REJECT
    score:        int                              # 0~100
    reasons:      list[str] = _field(default_factory=list)
    warnings:     list[str] = _field(default_factory=list)
    block_reason: str = ""
    verdict:      str = ""                         # PASS / WARN / BLOCK_RECOMMENDED / REJECT


# ─── verdict 분류 — 안전 위반만 REJECT, 그 외 등급별 경고 ─────────────
_SAFETY_VIOLATION_KEYWORDS = (
    "음모론",
    "발명",
    "익명 소식통",
    "금지어",
    "매수 권유",
    "자동매매",
    "W2 실패",          # writing_scorer W2 (발명 신호)
    "W4 실패",          # writing_scorer W4 (날짜 정책 — 1년 초과 차단 케이스)
)


def _classify_verdict(grade: str, reasons: list[str]) -> str:
    """grade + reasons 기반 verdict 분류.

    - 안전 룰 위반 (음모론/발명/금지어/익명소식통/매수권유/자동매매/W2/W4 차단)
      → REJECT (전송 차단)
    - grade=='REJECT' 인데 안전 위반 없음 → BLOCK_RECOMMENDED (경고 + 전송)
    - grade=='C' → BLOCK_RECOMMENDED (경고 + 전송)
    - grade=='B' → WARN (경고 + 전송)
    - 그 외 (A/B 통과)  → PASS
    """
    reason_text = " ".join(reasons or [])
    if any(kw in reason_text for kw in _SAFETY_VIOLATION_KEYWORDS):
        return "REJECT"
    if grade == "REJECT":
        return "BLOCK_RECOMMENDED"
    if grade == "C":
        return "BLOCK_RECOMMENDED"
    if grade == "B":
        return "WARN"
    return "PASS"


# ─── 헬퍼 ────────────────────────────────────────────────────────────
def _count_confirmed_facts(handoff: dict) -> int:
    facts = handoff.get("confirmed_facts", [])
    if isinstance(facts, list):
        return len([f for f in facts if f and len(str(f).strip()) > 10])
    if isinstance(facts, str) and len(facts.strip()) > 10:
        return 1
    return 0


def json_to_text(handoff: dict) -> str:
    """핸드오프 dict 를 단일 텍스트로."""
    parts: list[str] = []
    for v in handoff.values():
        if isinstance(v, str):
            parts.append(v)
        elif isinstance(v, list):
            parts.extend(str(i) for i in v)
        elif isinstance(v, dict):
            parts.append(json_to_text(v))
    return " ".join(parts)


def _has_external_comparison(handoff: dict) -> bool:
    angle_text = " ".join([
        str(handoff.get("angle", "")),
        str(handoff.get("core_tension", "")),
        str(handoff.get("frame", "")),
    ])
    original = str(handoff.get("original_draft", ""))
    for match in EXTERNAL_COMPARISON.finditer(angle_text):
        keyword = match.group()
        if keyword not in original:
            return True
    return False


def _count_causal_overreach(text: str) -> int:
    return len(CAUSAL_OVERREACH.findall(text or ""))


def _has_template_contamination(handoff: dict) -> bool:
    return bool(TEMPLATE_CONTAMINATION.search(json_to_text(handoff)))


def _has_duplicate_sections(handoff: dict) -> bool:
    all_text = json_to_text(handoff)
    return any(all_text.count(k) >= 3 for k in DUPLICATE_KEYS)


def _has_key_numbers(handoff: dict) -> bool:
    draft = str(handoff.get("original_draft", ""))
    pattern = re.compile(r"\d+[\d,\.]*\s*(%|bp|달러|원|조|억|만|%p|배)")
    return bool(pattern.search(draft))


# ─── 등급 산정 ───────────────────────────────────────────────────────
def _calculate_grade(
    fact_count: int,
    has_numbers: bool,
    has_external: bool,
    causal_count: int,
    has_contamination: bool,
    has_duplicate: bool,
) -> tuple[str, int, list[str]]:
    """A 금지 조건 카운트 + 점수 → grade."""
    a_block: list[str] = []

    if fact_count == 0:
        a_block.append("confirmed_facts 없음")
    if not has_numbers:
        a_block.append("핵심 숫자/고유명사 부족")
    if has_external:
        a_block.append("외부 비교축 오염")
    if causal_count >= 3:
        a_block.append(f"인과 과잉 표현 {causal_count}개")
    if has_contamination or has_duplicate:
        a_block.append("중복/오염 블록 존재")

    score = 100
    score -= (
        0  if fact_count >= 3 else
        10 if fact_count == 2 else
        20 if fact_count == 1 else
        40
    )
    score -= 0  if has_numbers else 15
    score -= 20 if has_external else 0
    score -= min(causal_count * 5, 20)
    score -= 15 if has_contamination else 0
    score -= 10 if has_duplicate else 0
    score = max(0, min(100, score))

    block_count = len(a_block)
    if block_count >= 3 or (fact_count == 0 and block_count >= 2):
        grade = "REJECT"
    elif block_count >= 2 or score < 50:
        grade = "C"
    elif block_count == 1 or score < 70:
        grade = "B"
    else:
        grade = "A"
    return grade, score, a_block


# ─── 자동 정리 ───────────────────────────────────────────────────────
def _auto_clean(handoff: dict) -> dict:
    """REWRITE_REQUIRED 용 비파괴 자동 정리.

    - 템플릿 오염 문구 제거
    - key_evidence 중복 항목 제거 (앞 50자 기준)
    - grade/angle/frame 손대지 않음.
    """
    cleaned = dict(handoff)
    for key, val in list(cleaned.items()):
        if isinstance(val, str):
            cleaned[key] = TEMPLATE_CONTAMINATION.sub(" ", val).strip()
        elif isinstance(val, list):
            cleaned[key] = [
                TEMPLATE_CONTAMINATION.sub(" ", str(v)).strip()
                for v in val
                if TEMPLATE_CONTAMINATION.sub(" ", str(v)).strip()
            ]
    evidence = cleaned.get("key_evidence", [])
    if isinstance(evidence, list):
        seen: set[str] = set()
        deduped: list = []
        for ev in evidence:
            head = str(ev).strip()[:50]
            if head and head not in seen:
                seen.add(head)
                deduped.append(ev)
        cleaned["key_evidence"] = deduped
    return cleaned


# ─── 메인 판정 함수 ───────────────────────────────────────────────────
def judge(handoff: dict) -> QualityVerdict:
    """핸드오프 품질 판정 — APPROVE / REWRITE_REQUIRED / REJECT.

    handoff dict 권장 키:
      original_draft, confirmed_facts, angle, core_tension, frame,
      key_evidence, grade_label, 훅 후보 / hook_candidates
    """
    all_text = json_to_text(handoff)
    fact_count = _count_confirmed_facts(handoff)
    has_numbers = _has_key_numbers(handoff)
    has_external = _has_external_comparison(handoff)
    causal_count = _count_causal_overreach(all_text)
    has_contamination = _has_template_contamination(handoff)
    has_duplicate = _has_duplicate_sections(handoff)

    grade, score, _block_reasons = _calculate_grade(
        fact_count, has_numbers, has_external,
        causal_count, has_contamination, has_duplicate,
    )

    reasons: list[str] = []
    warnings: list[str] = []
    if fact_count == 0:
        reasons.append("confirmed_facts 없음 — 강한 주장 근거 없음")
    elif fact_count == 1:
        warnings.append("confirmed_facts 1건 — 부족")
    if has_external:
        reasons.append("외부 비교축 오염 — 원문에 없는 angle 삽입")
    if causal_count >= 3:
        reasons.append(
            f"인과 과잉 표현 {causal_count}개 — evidence 없이 강한 주장"
        )
    if has_contamination:
        reasons.append("템플릿 오염 문구 감지")
    if has_duplicate:
        warnings.append("중복 섹션 감지 — 자동 정리 가능")

    # 훅 후보 + 핸드오프 필드 추가 검증 (Phase 3)
    try:
        hook_w, hook_b = _check_hook_candidates(handoff)
        field_w, field_b = _check_handoff_fields(handoff)
        reasons.extend(hook_b)
        reasons.extend(field_b)
        warnings.extend(hook_w)
        warnings.extend(field_w)
        # block 사유가 추가되면 grade 강등
        if (hook_b or field_b) and grade not in ("REJECT",):
            grade = "C"
    except Exception as _he:
        _judge_logger.debug(f"[HandoffGuard] hook/field 확장 검증 skip: {_he}")

    # 결정 산출 (Phase 4 writing_score 통합 전 임시값)
    if grade == "REJECT":
        decision = "REJECT"
        block_reason = " / ".join(reasons[:3]) or "재료 품질 부족"
    elif grade == "C" or has_contamination or has_duplicate:
        decision = "REWRITE_REQUIRED"
        block_reason = ""
    else:
        decision = "APPROVE"
        block_reason = ""

    # Phase 4 — Writing OS v1 통합 (7원칙 채점 + 안전 게이트)
    try:
        reasons, warnings, grade, decision = _apply_writing_score(
            handoff, reasons, warnings, grade, decision,
        )
        if grade == "REJECT":
            block_reason = " / ".join(reasons[:3]) or block_reason or "writing_score 안전 게이트 실패"
    except Exception as _we:
        _judge_logger.debug(f"[HandoffGuard] writing_score skip: {_we}")

    if decision == "REJECT":
        _judge_logger.warning(
            f"[HandoffGuard] REJECT: {block_reason} (score={score})"
        )
    elif decision == "REWRITE_REQUIRED":
        _judge_logger.info(
            f"[HandoffGuard] REWRITE_REQUIRED grade={grade} score={score}"
        )
    else:
        _judge_logger.info(
            f"[HandoffGuard] APPROVE grade={grade} score={score}"
        )

    return QualityVerdict(
        decision=decision,
        grade=grade,
        score=score,
        reasons=reasons,
        warnings=warnings,
        block_reason=block_reason,
        verdict=_classify_verdict(grade, reasons),
    )


# ─── Phase 4 — Writing OS v1 통합 (7원칙 채점 게이트) ────────────────
def _apply_writing_score(
    handoff: dict,
    reasons: list,
    warnings: list,
    grade: str,
    decision: str,
) -> tuple[list, list, str, str]:
    """기존 judge 결과에 7원칙 writing_score 통합.

    안전 룰 (W2/W4/금지어) 실패 시 자동 REJECT.
    overall_score < 80 + 현재 REJECT 아니면 REWRITE_REQUIRED 로 강등.
    """
    draft_text = (
        handoff.get("original_draft")
        or handoff.get("draft")
        or handoff.get("content")
        or ""
    )
    if not draft_text:
        return reasons, warnings, grade, decision

    try:
        from app.services.writing_scorer import score_text as _ws_score
        ws = _ws_score(draft_text)
    except Exception as e:
        _judge_logger.debug(f"[Phase4] writing_scorer 호출 실패 (skip): {e}")
        return reasons, warnings, grade, decision

    # 안전 게이트 — REJECT 강제
    if not ws.w2_no_invention:
        reasons.append("W2 실패: 익명 소식통/발명 신호")
        grade = "REJECT"; decision = "REJECT"
    if not ws.w4_date_policy:
        reasons.append("W4 실패: 날짜 정책 위반")
        grade = "REJECT"; decision = "REJECT"
    if ws.forbidden_hits > 0:
        reasons.append(f"금지어 {ws.forbidden_hits}건")
        grade = "REJECT"; decision = "REJECT"

    # 권고 (warning)
    if not ws.w1_hook_pattern:
        warnings.append("W1: 첫 문장 패턴 개선 권장")
    if not ws.w6_nut_graf:
        warnings.append("W6: nut graf 없음")
    if not ws.w7_follow_reason:
        warnings.append("W7: 팔로우 이유 부족")

    # 점수 강등 — REJECT 아닐 때만
    if ws.overall_score < 80 and decision != "REJECT":
        if grade not in ("C", "REJECT"):
            grade = "C"
        decision = "REWRITE_REQUIRED"

    return reasons, warnings, grade, decision


# ─── Phase 3 훅·필드 검증 ─────────────────────────────────────────────
EMOJI_PATTERN = re.compile(
    "["
    "\U0001F300-\U0001F9FF"
    "\U00002600-\U000027BF"
    "\U0001FA00-\U0001FAFF"
    "]"
)


def _check_hook_candidates(handoff: dict) -> tuple[list, list]:
    """훅 후보 검증. 반환: (warnings, blocks)."""
    warnings: list = []
    blocks: list = []

    hook_section = ""
    for key in ("훅 후보", "hook_candidates", "반드시 살릴 포인트"):
        v = handoff.get(key)
        if v:
            hook_section = str(v) if not isinstance(v, list) else "\n".join(map(str, v))
            break
    if not hook_section:
        return warnings, blocks  # 섹션 없으면 검증 skip (warning 도 안 함)

    lines = [l.strip() for l in hook_section.split("\n") if l.strip()]
    banned_words = (
        "주목해야 할", "흥미로운", "충격적인", "폭발적", "급격히",
    )
    for line in lines[:5]:
        # 번호/패턴/자수 prefix 제거
        hook_text = re.sub(r"^\s*\d+\.\s*", "", line)
        hook_text = re.sub(r"\[패턴.\]\s*", "", hook_text)
        hook_text = re.sub(r"\(\d+자\)\s*", "", hook_text).strip()
        if not hook_text:
            continue
        char_count = len(hook_text)

        if char_count > 25:
            blocks.append(f"훅 25자 초과 ({char_count}자): {hook_text[:30]}")
        elif char_count < 14:
            warnings.append(f"훅 14자 미만 ({char_count}자)")

        if hook_text.endswith("."):
            blocks.append(f"훅 마침표 포함: {hook_text[:30]}")
        if "—" in hook_text or " - " in hook_text:
            blocks.append(f"훅 대시 포함 (설명형): {hook_text[:30]}")
        if EMOJI_PATTERN.search(hook_text):
            blocks.append(f"훅 이모지 포함: {hook_text[:30]}")

        for word in banned_words:
            if word in hook_text:
                warnings.append(f"훅 약한 표현 '{word}': {hook_text[:30]}")
    return warnings, blocks


def _check_handoff_fields(handoff: dict) -> tuple[list, list]:
    """핸드오프 필드 품질 검증."""
    warnings: list = []
    blocks: list = []

    # 이모지 헤더 과다 (헤드라인 뉴스 형식)
    emoji_headers = ("⚠️", "📌", "💎", "🔥", "🎯")
    try:
        full_text = json.dumps(handoff, ensure_ascii=False)
    except Exception:
        full_text = json_to_text(handoff)
    emoji_count = sum(full_text.count(e) for e in emoji_headers)
    if emoji_count >= 3:
        blocks.append(
            f"핸드오프 이모지 헤더 {emoji_count}개 (헤드라인 뉴스 형식)"
        )

    grade_reason = (
        handoff.get("살릴_가치_사유")
        or handoff.get("grade_reason")
        or handoff.get("살릴 가치")
        or ""
    )
    if grade_reason:
        abstract_phrases = (
            "회사/기관 맥락 부족",
            "보완 시 상위권",
            "추가 정보 시",
        )
        if any(p in str(grade_reason) for p in abstract_phrases):
            warnings.append(
                "살릴 가치 사유 추상적 (구체적 결함 명시 필요)"
            )

    edit_goal = (
        handoff.get("편집_목표")
        or handoff.get("edit_goal")
        or handoff.get("editorial_goal")
        or ""
    )
    if edit_goal and len(str(edit_goal)) > 100:
        warnings.append(f"편집 목표 너무 김 ({len(edit_goal)}자)")

    return warnings, blocks


# ─── pack 변환 어댑터 ────────────────────────────────────────────────
def judge_for_pack(
    source_pack: dict | None,
    angle_pack: dict | None = None,
    final_body: str = "",
    editorial_meta: dict | None = None,
) -> QualityVerdict:
    """source_pack/angle_pack/final_body 를 handoff dict 로 변환 후 judge.

    run_quality_guard 와 동일 입력으로 호출 가능 (orchestrator 자연 연동).
    """
    sp = source_pack or {}
    ap = angle_pack or sp.get("angle_pack") or {}
    em = editorial_meta or {}
    winner = ap.get("winner_angle") or {}
    handoff = {
        "original_draft":   final_body or "",
        "confirmed_facts":  sp.get("confirmed_facts") or [],
        "angle":            str(winner.get("angle") or ""),
        "core_tension":     str(ap.get("core_tension") or ""),
        "frame":            str(ap.get("frame_type") or ""),
        "key_evidence":     sp.get("evidence_pack") or [],
        "grade_label":      str(em.get("grade") or ""),
    }
    return judge(handoff)


# ─── draft_1465 회귀 샘플 ────────────────────────────────────────────
DRAFT_1465_SAMPLE = {
    "original_draft": (
        "물가는 늘 오르기만 했다. 1960년 45세로 햄버거 한 개를 "
        "사 먹었는데, 지금은 겨우 12조각이다. "
        "연 10% 인플레이션이 발생하면 화폐 가치가 10% 하락하고, "
        "이는 10%의 부유세를 내는 것과 같다."
    ),
    "confirmed_facts": [],
    "angle": (
        "Korea angle: 지금까지 몰라도 됐지만 이제 알아야 할 때입니다 "
        "기억을 더듬어 보면 물가는 늘 오르기만 했던 거 같습니다 "
        "0:13 오른다고 할 때마다 저항감이 들죠"
    ),
    "core_tension": "Uncertainty on record: 1960년 45세로 햄버거 1개",
    "key_evidence": [
        "0:13 오른다고 할 때마다 저항감이 들죠...",
        "0:13 오른다고 할 때마다 저항감이 들죠...",  # 중복
    ],
    "grade_label": "A",
}


def run_sample_test() -> QualityVerdict:
    """draft_1465 가 REJECT/REWRITE_REQUIRED 로 잡히는지 검증."""
    verdict = judge(DRAFT_1465_SAMPLE)
    _judge_logger.info(
        f"[Sample] draft_1465 → decision={verdict.decision} "
        f"grade={verdict.grade} score={verdict.score}"
    )
    assert verdict.decision in ("REJECT", "REWRITE_REQUIRED"), (
        f"draft_1465 는 REJECT/REWRITE_REQUIRED 여야 함. "
        f"실제: {verdict.decision}"
    )
    return verdict
