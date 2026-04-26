"""글 품질 채점 v2 — 안전 룰만 게이트, 글쓰기 룰은 참고용.

170+ 룰 → 6 룰로 축소 (S1·S2·S3 안전 + W1·W2·W3 참고).
W1~W7 강제 채점 / 한국 시장 연결 강제 / 외부 비교 차단 등 전면 폐기.

pass_gate = 안전 룰 (S1·S2·S3 + 금지 ending) 통과만.
글쓰기 점수는 score 만 영향 (게이트 아님).
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from app.editorial_constitution import FORBIDDEN_TERMS_V2

logger = logging.getLogger(__name__)


# ─── 안전 룰 보조 패턴 ───────────────────────────────────────────────
INVENTION_SIGNALS = (
    "익명의", "관계자에 따르면",
    "내부 소식통", "미확인 소식통",
)

CONSPIRACY_SIGNALS = (
    "일루미나티", "프리메이슨", "딥스테이트",
    "오컬트", "음모", "비밀결사",
    "미리 알고 있었", "엘리트 계층의 음모",
)

FORBIDDEN_ENDINGS = [
    re.compile(r".*리트윗\s*부탁.*$"),
    re.compile(r".*RT\s*해주세요.*$"),
    re.compile(r".*매수\s*추천.*$"),
    re.compile(r".*투자\s*권유.*$"),
]


# ─── 글쓰기 룰 보조 패턴 (참고용 점수 산출) ──────────────────────────
_NUMBER_RE = re.compile(r"\d+[\d,]*\s*(억|조|달러|원|%|bp|명|배)")
_TIME_RE = re.compile(r"(\d{1,2}월|\d{4}년|(새벽|오전|오후)\s*\d)")
_ACTIVE_VERBS_RE = re.compile(
    r"(줄었|늘었|넘었|내렸|올랐|멈췄|"
    r"떨어졌|올라갔|기록했|발표했)"
)
_OPENER_KEYWORDS = ("처음이다", "넘었다", "무너졌다", "끝났다", "아니다")
_NUT_SIGNALS = ("의미", "관전", "다음", "이유", "시사", "중요", "그래서")


@dataclass
class WritingScore:
    # 안전 (게이트)
    safe_no_invention:    bool = True
    safe_no_solicitation: bool = True
    safe_no_conspiracy:   bool = True

    # 글쓰기 (참고용, 강제 아님)
    has_strong_opener: bool = False
    has_scene:         bool = False
    has_nut_graf:      bool = False

    # 금지어
    forbidden_hits:   int  = 0
    forbidden_ending: bool = False

    # 결과
    overall_score: int  = 0
    pass_gate:     bool = False
    issues:        list = field(default_factory=list)
    enrich_needed: list = field(default_factory=list)


def score_text(text: str, sources=None) -> WritingScore:
    """6 룰 기반 채점. 안전 룰만 게이트.

    sources 파라미터는 v1 호환 위해 유지하되 v2 에서는 사용 안 함.
    """
    issues: list = []
    text = text or ""
    score = 70  # 기본 70점 (안전 통과 시)

    lines = [l.strip() for l in text.splitlines() if l.strip()]
    first = lines[0] if lines else ""
    last = lines[-1] if lines else ""

    # ── 안전 룰 (게이트)
    safe_invention = not any(s in text for s in INVENTION_SIGNALS)
    if not safe_invention:
        issues.append("S1: 익명 소식통 감지")

    forbidden_hits = sum(text.count(t) for t in FORBIDDEN_TERMS_V2)
    safe_solicitation = forbidden_hits == 0
    if not safe_solicitation:
        issues.append(f"S2: 금지어 {forbidden_hits}건")

    safe_conspiracy = not any(s in text for s in CONSPIRACY_SIGNALS)
    if not safe_conspiracy:
        issues.append("S3: 음모론 신호 감지")

    forbidden_ending = any(p.search(last) for p in FORBIDDEN_ENDINGS)
    if forbidden_ending:
        issues.append("S2: 금지 ending 감지")

    # ── 글쓰기 룰 (참고용)
    has_strong_opener = bool(
        _NUMBER_RE.search(first)
        or _TIME_RE.search(first)
        or any(k in first for k in _OPENER_KEYWORDS)
    )
    has_scene = bool(
        _ACTIVE_VERBS_RE.search(text)
        and (_NUMBER_RE.search(text) or _TIME_RE.search(text))
    )
    has_nut = any(s in last for s in _NUT_SIGNALS)

    # ── 점수 계산
    if has_strong_opener:
        score += 10
    if has_scene:
        score += 10
    if has_nut:
        score += 10
    if not safe_invention:
        score -= 40
    if not safe_solicitation:
        score -= 30
    if not safe_conspiracy:
        score -= 50
    if forbidden_ending:
        score -= 20
    score = max(0, min(100, score))

    # ── pass_gate: 안전 룰 + ending 만
    pass_gate = (
        safe_invention
        and safe_solicitation
        and safe_conspiracy
        and not forbidden_ending
    )

    # ── 보강 필요 (선택적, 자동 호출 안 함)
    enrich_needed: list = []
    if not has_strong_opener:
        enrich_needed.append("W1")
    if not has_nut:
        enrich_needed.append("W6")

    return WritingScore(
        safe_no_invention=safe_invention,
        safe_no_solicitation=safe_solicitation,
        safe_no_conspiracy=safe_conspiracy,
        has_strong_opener=has_strong_opener,
        has_scene=has_scene,
        has_nut_graf=has_nut,
        forbidden_hits=forbidden_hits,
        forbidden_ending=forbidden_ending,
        overall_score=score,
        pass_gate=pass_gate,
        issues=issues,
        enrich_needed=enrich_needed,
    )


def format_score_for_telegram(ws: WritingScore) -> str:
    """텔레그램 채점 카드 — 6 룰 간결 표시."""
    status = "✅ PASS" if ws.pass_gate else "❌ BLOCK"
    lines = [
        f"📐 {status} | {ws.overall_score}점",
        f"S1 발명 없음:   {'✅' if ws.safe_no_invention else '❌'}",
        f"S2 권유 없음:   {'✅' if ws.safe_no_solicitation else '❌'}",
        f"S3 음모론 없음: {'✅' if ws.safe_no_conspiracy else '❌'}",
        "",
        "글쓰기 (참고용):",
        f"W1 강한 첫줄:   {'✅' if ws.has_strong_opener else '·'}",
        f"W2 장면화:      {'✅' if ws.has_scene else '·'}",
        f"W3 nut graf:    {'✅' if ws.has_nut_graf else '·'}",
    ]
    if ws.issues:
        lines.append("")
        lines.append("문제: " + " / ".join(ws.issues))
    return "\n".join(lines)
