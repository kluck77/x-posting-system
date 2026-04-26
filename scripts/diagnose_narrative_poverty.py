"""
diagnose_narrative_poverty.py
==============================
Draft 1390 (일본-호주 함정 수출 건) 의 상류 파이프라인 각 단계 출력물을
정량 분석하여 서사 재료 누락 지점을 특정한다.

Phase 3a 진단 전용. 영구 도구 아님.

실행:
    python scripts/diagnose_narrative_poverty.py \
        > diagnose_logs/narrative_$(date +%Y%m%d_%H%M).log 2>&1

주의:
- 실 sidecar 는 서버(/root/x-posting-system/runtime_x/packs/1390.json) 에만 있음.
  로컬은 "sidecar 없음" 로그만 찍힘 — 정상. 서버에서 재실행해야 진짜 측정.
- CNBC 원기사 자동 비교는 하지 않음. 하드코딩된 예상 정보 리스트 기반
  수동 대조. 운영자가 CNBC 기사를 직접 확인한 결과로 해석할 것.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

# 프로젝트 루트 import 경로
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

TARGET_DRAFT_ID = 1390
SIDECAR_PATH = Path(f"/root/x-posting-system/runtime_x/packs/{TARGET_DRAFT_ID}.json")

# ─── 측정 도우미 ────────────────────────────────────────────────────────

_META_FACT_PATTERNS = (
    "확정 사실이 공급되지 않", "확정 사실 공급 안",
    "새 숫자", "고유명사 추가 금지",
    "숫자·고유명사", "숫자/고유명사",
    "날짜는 초안 그대로",
    "(none)", "n/a",
)

_ALPHA_RE = re.compile(r"[A-Za-z]")
_KOR_RE = re.compile(r"[가-힣]")
_WORD_RE = re.compile(r"[\w가-힣]")
_NUM_RE = re.compile(r"\d")
# 대문자 Latin 연속 2자+ 또는 한국어 기관/회사명 후보
_PROPER_NOUN_LATIN = re.compile(r"\b[A-Z][A-Za-z0-9&\.\-]{1,24}\b")
_PROPER_NOUN_KR = re.compile(
    r"(정부|은행|금융위|공정위|국회|총리실|산업부|기재부|검찰|경찰|"
    r"삼성|현대|SK|LG|네이버|카카오|미쓰비시|JAXA|방위성|해군|자위대|"
    r"보잉|록히드|BAE)"
)
_DATE_RE = re.compile(
    r"(20\d{2}|Q[1-4]|\d{1,2}/\d{1,2}|\d{1,2}\s*월\s*\d{1,2}\s*일|"
    r"\d{1,2}\s*월|\d{1,2}\s*일|\d{1,2}\s*분기|상반기|하반기|연말|연초)"
)
_QUOTE_RE = re.compile(r"[\"“”]([^\"“”]{3,})[\"“”]|'([^']{3,})'")
_CAUSAL_RE = re.compile(r"(따라서|때문에|그 결과|이로 인해|so that|therefore)")
_CONTRAST_RE = re.compile(r"(그러나|반면|하지만|한편|대비해|unlike|in contrast)")


def _english_ratio(text: str) -> float:
    if not text:
        return 0.0
    alpha = len(_ALPHA_RE.findall(text))
    total = len(_WORD_RE.findall(text))
    return (alpha / total) if total else 0.0


def _korean_ratio(text: str) -> float:
    if not text:
        return 0.0
    kor = len(_KOR_RE.findall(text))
    total = len(_WORD_RE.findall(text))
    return (kor / total) if total else 0.0


def _is_meta_fact(text: str) -> bool:
    low = text.lower()
    return any(p.lower() in low for p in _META_FACT_PATTERNS)


def _collect_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return " ".join(str(x) for x in value if x is not None)
    if isinstance(value, dict):
        return " ".join(_collect_text(v) for v in value.values())
    return ""


def _split_sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"[\.\?!。？！]+|\n+", text) if s.strip()]


# ─── 1. source_pack richness ───────────────────────────────────────────

def measure_source_pack_richness(source_pack: dict) -> dict:
    facts = source_pack.get("confirmed_facts") or []
    facts = facts if isinstance(facts, list) else []
    real = [f for f in facts if isinstance(f, str) and f.strip() and not _is_meta_fact(f)]
    total_text = _collect_text(source_pack)
    proper_latin = len(_PROPER_NOUN_LATIN.findall(total_text))
    proper_kr = len(_PROPER_NOUN_KR.findall(total_text))
    return {
        "confirmed_facts_count": len(facts),
        "confirmed_facts_real_count": len(real),
        "confirmed_facts_avg_len": round(
            sum(len(f) for f in real) / len(real), 1
        ) if real else 0,
        "proper_noun_hits_latin": proper_latin,
        "proper_noun_hits_korean": proper_kr,
        "numeric_tokens_count": len(_NUM_RE.findall(total_text)),
        "date_tokens_count": len(_DATE_RE.findall(total_text)),
        "quote_marks_count": len(_QUOTE_RE.findall(total_text)),
        "korean_ratio": round(_korean_ratio(total_text), 3),
        "english_ratio": round(_english_ratio(total_text), 3),
        "raw_fields_summary": {
            k: f"{type(v).__name__}(len={len(v) if hasattr(v, '__len__') else '-'})"
            for k, v in source_pack.items()
        },
    }


# ─── 2. angle_pack richness ────────────────────────────────────────────

def measure_angle_pack_richness(angle_pack: dict) -> dict:
    wa = angle_pack.get("winner_angle") if isinstance(angle_pack, dict) else {}
    wa = wa if isinstance(wa, dict) else {}
    angle = wa.get("angle") or ""
    reason = wa.get("reason") or ""
    is_heuristic = False
    low = reason.lower() if isinstance(reason, str) else ""
    if "heuristic" in low or "fallback" in low:
        is_heuristic = True
    method = angle_pack.get("method") if isinstance(angle_pack, dict) else None
    if isinstance(method, str) and "fallback" in method.lower():
        is_heuristic = True
    # 잘림 감지: 영어 텍스트가 공백 없이 the/a/of/in 같은 관사/전치사로 끝나면 truncated
    truncated = False
    if isinstance(angle, str) and len(angle) > 10:
        tail = angle.rstrip().lower()[-12:]
        if re.search(r"\b(the|a|an|of|in|on|at|for|with)\s*$", tail):
            truncated = True
        if angle.endswith(",") or angle.endswith("—"):
            truncated = True
    # 동사 포함 여부 (간이 휴리스틱)
    has_verb = bool(re.search(
        r"(이다|되다|있다|없다|했다|한다|하다|추진|발표|공개|is|was|has|plans|signed|won)",
        angle
    ))
    # editorial_goal 품질
    eg = angle_pack.get("editorial_goal") if isinstance(angle_pack, dict) else None
    eg_quality = "missing"
    if isinstance(eg, str) and eg.strip():
        if "heuristic" in eg.lower() or "fallback" in eg.lower():
            eg_quality = "placeholder"
        else:
            eg_quality = "real"
    return {
        "is_heuristic_fallback": is_heuristic,
        "winner_angle_length": len(angle) if isinstance(angle, str) else 0,
        "winner_angle_is_truncated": truncated,
        "winner_angle_has_verb": has_verb,
        "winner_angle_reason_value": reason[:80] if isinstance(reason, str) else "",
        "frame_type": angle_pack.get("frame_type") if isinstance(angle_pack, dict) else None,
        "story_spine": angle_pack.get("story_spine") if isinstance(angle_pack, dict) else None,
        "readability_risk": angle_pack.get("readability_risk") if isinstance(angle_pack, dict) else None,
        "share_trigger": angle_pack.get("share_trigger") if isinstance(angle_pack, dict) else None,
        "editorial_goal_quality": eg_quality,
    }


# ─── 3. draft body richness ────────────────────────────────────────────

def measure_draft_body_richness(draft_body: str) -> dict:
    body = draft_body or ""
    sentences = _split_sentences(body)
    num_tokens = len(_NUM_RE.findall(body))
    proper_nouns = len(_PROPER_NOUN_LATIN.findall(body)) + len(_PROPER_NOUN_KR.findall(body))
    direct_quotes = len(_QUOTE_RE.findall(body))
    time_anchors = len(_DATE_RE.findall(body))
    causal = len(_CAUSAL_RE.findall(body))
    contrast = len(_CONTRAST_RE.findall(body))
    # narrative_score: 구체성(수치+고유명사) 40% + 인용 20% + 시점 앵커 20% + 대조/인과 20%
    score = 0.0
    score += min(num_tokens * 5, 20)
    score += min(proper_nouns * 3, 20)
    score += min(direct_quotes * 10, 20)
    score += min(time_anchors * 5, 20)
    score += min((causal + contrast) * 5, 20)
    score = min(score, 100)
    return {
        "total_chars": len(body),
        "sentence_count": len(sentences),
        "numeric_tokens": num_tokens,
        "proper_nouns": proper_nouns,
        "direct_quotes": direct_quotes,
        "time_anchors": time_anchors,
        "causal_connectors": causal,
        "contrast_connectors": contrast,
        "narrative_score": round(score, 1),
    }


# ─── 4. CNBC article comparison ────────────────────────────────────────

# CNBC 2026-04-20 "Australia picks Japan Mogami-class frigates over Germany"
# 운영자가 기사를 직접 확인한 정보 항목. 웹 fetch 가 어려운 환경이라 하드코딩.
# 기사 공개 정보에서 통상 확인 가능한 핵심 사항들 — 실 기사에 있는지 여부는
# 운영자가 확인 후 필요 시 리스트 조정.
EXPECTED_INFO_ITEMS = [
    ("계약 규모 (금액/조 단위)",              ["trillion", "billion", "조 원", "조 엔", "억 달러"]),
    ("함정 모델명 (Mogami-class 등)",         ["mogami", "모가미"]),
    ("조달 척수 (호주 측 도입 수)",           ["척", "ship", "frigate", "vessel"]),
    ("인도 일정 (착공/납기 시점)",             ["2028", "2029", "2030", "2031", "납기", "인도"]),
    ("경쟁 실패국 (독일 등)",                  ["germany", "독일", "ThyssenKrupp", "MEKO"]),
    ("일본 정부 관계자 발언 (직접 인용)",      ["방위상", "총리", "said", "stated"]),
    ("호주 정부 관계자 발언 (직접 인용)",      ["호주 총리", "australian pm", "albanese", "marles"]),
    ("배경 긴장 (중국/인도-태평양)",          ["china", "중국", "indo-pacific", "인도-태평양"]),
    ("일본 무기 수출 3원칙 변경 맥락",         ["3원칙", "three principles", "수출 금지", "export ban"]),
    ("기술 이전 / 현지 건조 조건",             ["technology transfer", "기술 이전", "local build", "현지"]),
]


def compare_with_source_article(draft_body: str, source_pack: dict) -> list[dict]:
    """
    draft + source_pack 에 EXPECTED_INFO_ITEMS 가 나타나는지 체크.
    실 기사 대비 커버리지 추정 (자동 fetch 없이 키워드 매칭 기반).
    """
    sp_text = _collect_text(source_pack).lower()
    db_text = (draft_body or "").lower()
    results = []
    for label, keywords in EXPECTED_INFO_ITEMS:
        in_source = any(k.lower() in sp_text for k in keywords)
        in_draft = any(k.lower() in db_text for k in keywords)
        results.append({
            "item": label,
            "in_source_pack": in_source,
            "in_draft_body": in_draft,
            "keywords_checked": keywords[:3],
        })
    return results


# ─── loader ─────────────────────────────────────────────────────────────

def load_sidecar() -> dict | None:
    if not SIDECAR_PATH.exists():
        return None
    try:
        return json.loads(SIDECAR_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"!!! sidecar 파싱 실패: {type(e).__name__}: {e}")
        return None


# ─── main ──────────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 70)
    print(f"DRAFT {TARGET_DRAFT_ID} NARRATIVE POVERTY DIAGNOSIS")
    print("=" * 70)
    print(f"SIDECAR_PATH: {SIDECAR_PATH}")
    print(f"EXISTS: {SIDECAR_PATH.exists()}")

    sidecar = load_sidecar()
    if sidecar is None:
        print("\n!!! sidecar 없음 — 로컬 환경이면 서버에서 재실행 필요:")
        print("    cd /root/x-posting-system && python scripts/diagnose_narrative_poverty.py \\")
        print("        > /root/narrative_$(date +%Y%m%d_%H%M).log 2>&1")
        return

    source_pack = sidecar.get("source", {}) or {}
    angle_pack = sidecar.get("angle", {}) or {}
    draft_body = sidecar.get("final_body", "") or ""
    labels = sidecar.get("labels", {}) or {}
    handoff = sidecar.get("handoff", "") or ""

    print("\n[1] source_pack richness")
    sm = measure_source_pack_richness(source_pack)
    for k, v in sm.items():
        print(f"  {k}: {v}")

    print("\n[2] angle_pack richness")
    am = measure_angle_pack_richness(angle_pack)
    for k, v in am.items():
        print(f"  {k}: {v}")

    print("\n[3] draft body richness")
    dm = measure_draft_body_richness(draft_body)
    for k, v in dm.items():
        print(f"  {k}: {v}")

    print("\n[4] CNBC-expected info coverage (keyword 기반 추정)")
    comp = compare_with_source_article(draft_body, source_pack)
    print(f"  {'item':<40} {'source':<8} {'draft':<8}")
    for r in comp:
        sp_mark = "O" if r["in_source_pack"] else "X"
        db_mark = "O" if r["in_draft_body"] else "X"
        print(f"  {r['item'][:40]:<40} {sp_mark:<8} {db_mark:<8}")

    print("\n[5] labels (Phase 1 quality guard sidecar)")
    print(json.dumps(labels, indent=2, ensure_ascii=False, default=str)[:1500])

    print("\n[6] handoff 앞 1500자 (Grok 가 실제로 본 것)")
    print(handoff[:1500])

    print("\n[7] sidecar 전체 덤프 (보고서용, 5000자 이후 생략)")
    print(json.dumps(sidecar, indent=2, ensure_ascii=False, default=str)[:5000])
    print("... (이후 생략)")


if __name__ == "__main__":
    main()
