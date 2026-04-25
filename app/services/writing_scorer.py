"""글 품질 자동 채점 — 7원칙 기반.

pass_gate = 안전 룰(W2/W4/W5/금지어/금지 ending) 전부 통과 + score >= 80.
72개 금지어 → 24개로 축소 (매수·매도·발명·결과 약속만 유지).
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from app.services.date_validator import Source, validate_source

logger = logging.getLogger(__name__)

try:
    from zoneinfo import ZoneInfo
    KST = ZoneInfo("Asia/Seoul")
except ImportError:  # pragma: no cover
    from datetime import timezone, timedelta
    KST = timezone(timedelta(hours=9))


# ─── 24 금지어 (72개에서 핵심만 추림) ────────────────────────────────
FORBIDDEN_TERMS = [
    # 매수·매도 권유
    "지금 사야", "지금 팔아야", "무조건 매수",
    "무조건 매도", "100% 상승", "100% 하락",
    # 자동매매·리딩방
    "자동매매", "복사트레이딩", "텔레그램 단톡방",
    "리딩방", "투자 권유",
    # 단정형 결과 약속
    "확정", "보장", "반드시 오른다", "반드시 떨어진다",
    # 익명 소식통 (발명 위험)
    "관계자에 따르면", "익명의 소식통", "내부 소식통",
    # 선동
    "개미들은 모르는", "호구", "바보들만",
    # 결과 약속
    "조회수 폭발", "팔로워 보장",
    # 과장 동사
    "폭발한다", "붕괴한다", "대폭락", "대폭등",
]


FORBIDDEN_ENDINGS = [
    re.compile(r".*리트윗\s*부탁.*$"),
    re.compile(r".*RT\s*해주세요.*$"),
    re.compile(r".*매수\s*추천.*$"),
    re.compile(r".*투자\s*권유.*$"),
]


# W1 첫 문장 패턴 (좌표/임계값/모순/수치)
FIRST_LINE_PATTERNS = [
    re.compile(r"\d{1,2}월\s*\d{1,2}일"),
    re.compile(r"(새벽|오전|오후)\s*\d{1,2}시"),
    re.compile(r"\d{4}년\s*\d{1,2}월"),
    re.compile(r"(넘었다|돌파|처음이다|최초)"),
    re.compile(r".+(올랐|상승).+(내렸|하락)"),
    re.compile(r"(신고가|신저가).+(신고가|신저가)"),
    re.compile(r"\d+[\d,]*\s*(억|조|달러|원|%|bp)"),
]


_INVENTION_SIGNALS = ("익명의", "관계자에 따르면", "내부 소식통")


_SCENE_VERB_RE = re.compile(
    r"(줄었|늘었|넘었|내렸|올랐|멈췄|떨어졌|올라갔)"
)
_SCENE_COORD_RE = re.compile(
    r"\d{1,2}월|\d{4}년|(새벽|오전|오후)\d"
)


_SOURCE_SIGNAL_RE = re.compile(
    r"(한국은행|금융위|금감원|Fed|Bloomberg|Reuters|CoinDesk|"
    r"연합뉴스|뉴시스|한경|조선|중앙|공시|보고서|"
    r"https?://\S+)"
)


_NUT_SIGNALS = ("의미", "관전", "다음", "이유", "시사", "중요")
_INTERP_SIGNALS = ("나는", "읽힌다", "드러난다", "가리킨다", "의미하는")
_NEXT_SIGNALS = ("다음", "앞으로", "남은", "까지")


@dataclass
class WritingScore:
    w1_hook_pattern:     bool          # +20
    w2_no_invention:     bool          # 안전 게이트
    w3_scene_conversion: bool          # +10
    w4_date_policy:      bool          # 안전 게이트
    w5_source_cited:     bool          # 안전 게이트
    w6_nut_graf:         bool          # +15
    w7_follow_reason:    bool          # +10
    forbidden_hits:      int           # -30/건
    forbidden_ending:    bool          # -20
    avg_sentence_len:    float
    overall_score:       int
    pass_gate:           bool
    issues:              list[str]


def score_text(
    text: str,
    sources: Optional[list[Source]] = None,
) -> WritingScore:
    """7원칙 기반 글 채점."""
    issues: list[str] = []
    score = 50
    sources = sources or []
    today = datetime.now(KST)
    text = text or ""

    lines = [l.strip() for l in text.splitlines() if l.strip()]
    first_line = lines[0] if lines else ""
    last_line = lines[-1] if lines else ""

    # W1 — 첫 문장 패턴
    w1 = any(p.search(first_line) for p in FIRST_LINE_PATTERNS)
    if w1:
        score += 20
    else:
        issues.append("W1: 첫 문장 패턴 미충족 (좌표/모순/임계값 없음)")

    # W2 — 발명 신호 감지
    w2 = not any(s in text for s in _INVENTION_SIGNALS)
    if not w2:
        issues.append("W2: 익명 소식통 또는 발명 신호 감지")

    # W3 — 장면화 (좌표 + 능동 동사)
    has_coord = bool(_SCENE_COORD_RE.search(text))
    has_active = bool(_SCENE_VERB_RE.search(text))
    w3 = has_coord and has_active
    if w3:
        score += 10
    else:
        issues.append("W3: 장면화 부족 (좌표 또는 능동 동사 없음)")

    # W4 — 날짜 정책
    date_results = [validate_source(s, today) for s in sources]
    has_blocked = any(r.status == "blocked" for r in date_results)
    has_unknown_unlabeled = (
        any(r.status == "unknown" for r in date_results)
        and "미확인" not in text
        and "추정" not in text
    )
    w4 = (not has_blocked) and (not has_unknown_unlabeled)
    if has_blocked:
        score -= 50
        issues.append("W4: 1년 초과 자료 차단")
    if has_unknown_unlabeled:
        score -= 25
        issues.append("W4: 미확인 자료에 라벨 누락")

    # W5 — 출처 (URL 또는 기관명)
    has_source_signal = bool(_SOURCE_SIGNAL_RE.search(text))
    w5 = has_source_signal or len(sources) > 0
    if not w5:
        issues.append("W5: 출처 신호 없음")

    # W6 — Nut graf (마지막 줄 의미 부여)
    w6 = any(s in last_line for s in _NUT_SIGNALS)
    if w6:
        score += 15
    else:
        issues.append("W6: nut graf 없음 (마지막 줄 의미 부재)")

    # W7 — 팔로우 이유 (정보 + 해석 + 다음)
    has_info = any(re.search(r"\d", l) for l in lines)
    has_interp = any(s in text for s in _INTERP_SIGNALS)
    has_next = any(s in text for s in _NEXT_SIGNALS)
    w7 = has_info and (has_interp or has_next)
    if w7:
        score += 10
    else:
        issues.append("W7: 팔로우 이유 부족 (정보+해석+다음 관전 중 부족)")

    # 금지어
    hits = sum(text.count(t) for t in FORBIDDEN_TERMS)
    if hits > 0:
        score -= 30 * hits
        issues.append(f"금지어 {hits}건 발견")

    # 금지 ending
    fe = any(p.search(last_line) for p in FORBIDDEN_ENDINGS)
    if fe:
        score -= 20
        issues.append("금지 ending 발견")

    # 평균 문장 길이
    sents = [s for s in re.split(r"[.!?。]\s*", text) if s.strip()]
    avg_len = sum(len(s) for s in sents) / len(sents) if sents else 0.0

    overall = max(0, min(100, score))
    pass_gate = (
        w2 and w4 and w5
        and hits == 0
        and not fe
        and overall >= 80
    )

    return WritingScore(
        w1_hook_pattern=w1,
        w2_no_invention=w2,
        w3_scene_conversion=w3,
        w4_date_policy=w4,
        w5_source_cited=w5,
        w6_nut_graf=w6,
        w7_follow_reason=w7,
        forbidden_hits=hits,
        forbidden_ending=fe,
        avg_sentence_len=round(avg_len, 1),
        overall_score=overall,
        pass_gate=pass_gate,
        issues=issues,
    )


def format_score_for_telegram(score: WritingScore) -> str:
    """텔레그램 채점 카드 — 7원칙 표 + 점수 + 이슈."""
    status = "✅ PASS" if score.pass_gate else "❌ BLOCK"
    lines = [
        f"{status} | 점수: {score.overall_score}/100",
        "",
        f"W1 첫문장 패턴: {'✅' if score.w1_hook_pattern else '❌'}",
        f"W2 발명 없음:   {'✅' if score.w2_no_invention else '❌'}",
        f"W3 장면화:      {'✅' if score.w3_scene_conversion else '❌'}",
        f"W4 날짜 정책:   {'✅' if score.w4_date_policy else '❌'}",
        f"W5 출처:        {'✅' if score.w5_source_cited else '❌'}",
        f"W6 Nut graf:    {'✅' if score.w6_nut_graf else '❌'}",
        f"W7 팔로우 이유: {'✅' if score.w7_follow_reason else '❌'}",
    ]
    if score.issues:
        lines.append("")
        lines.append("문제:")
        for issue in score.issues:
            lines.append(f"  · {issue}")
    return "\n".join(lines)
