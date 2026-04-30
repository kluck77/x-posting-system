"""
INFO VALUE GATE v1
==================
초안 생성 전 단계에서 "이 소재가 작성/게시할 가치가 있는가?" 를
heuristic 으로 판정한다.

핵심 원칙:
- 새로운 AI 호출 없음 (heuristic 만 사용)
- 기존 research_summary / factcheck_summary 결과를 단서로 활용
- fail-open : 어떤 분기에서도 예외 시 안전한 기본값 반환

평가 결과 (dict):
- score (0-100)
- action_label : PUBLISH / VERIFY_MORE / COMMENT_ONLY / RESEARCH_REQUIRED / DROP
- 8 sub-scores : info_rarity / trust_level / reader_value /
                  interpretation_potential / timing / differentiation /
                  risk_level / recommended_format
- forbidden_claims : 본 소재로 절대 쓰면 안 되는 클레임 리스트
- 분석 카드용 필드 : why_useful / why_risky / draft_input_focus /
                    confirmed_facts / uncertain_parts

Thin Query Guard:
  source_type ∈ {manual, community_input, topic_search} +
  source_text 짧고 (< 200) + url 없고 + 트랜스크립트 표지 없음
  → RESEARCH_REQUIRED 강제 + score < 50

설계: minimal heuristic, 외부 의존 없음 (stdlib 만).
"""

from __future__ import annotations

import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 임계값 / 라벨
# ---------------------------------------------------------------------------
_SCORE_PUBLISH = 85
_SCORE_VERIFY = 70
_SCORE_COMMENT = 50
_SCORE_RESEARCH = 30

ACTION_PUBLISH = "PUBLISH"
ACTION_VERIFY_MORE = "VERIFY_MORE"
ACTION_COMMENT_ONLY = "COMMENT_ONLY"
ACTION_RESEARCH_REQUIRED = "RESEARCH_REQUIRED"
ACTION_DROP = "DROP"

LEVEL_LOW = "low"
LEVEL_MEDIUM = "medium"
LEVEL_HIGH = "high"

TIMING_STALE = "stale"
TIMING_NORMAL = "normal"
TIMING_FRESH = "fresh"
TIMING_BREAKING = "breaking"

# Thin Query Guard 임계
_THIN_QUERY_MIN_LEN = 200
_THIN_QUERY_SOURCE_TYPES = {"manual", "community_input", "topic_search"}


# ---------------------------------------------------------------------------
# 패턴 — 위험 / 한국 맥락 / 신선도
# ---------------------------------------------------------------------------
_BETTING_PATTERNS = [
    r"polymarket", r"베팅", r"prediction\s*market", r"odds\b",
    r"카지노", r"bookmaker", r"\bdraftkings\b",
]
_FINANCE_RISK_PATTERNS = [
    r"매수\s*추천", r"매도\s*추천", r"목표주가", r"수익\s*보장",
    r"\bbuy\s+now\b", r"\bsell\s+now\b", r"price\s+target",
]
_KOREAN_POLITICAL_PATTERNS = [
    r"민주당", r"국민의힘", r"\b여당\b", r"\b야당\b",
    r"대통령\s*지지율", r"\b정당\b",
]
_KOREAN_EXPLICIT_PATTERNS = [
    r"\b한국\b", r"\b국내\b", r"\b코스피\b", r"\b원화\b",
    r"\b한국은행\b", r"\b서울\b", r"\b부산\b", r"\b국회\b",
]
_GLOBAL_ONLY_PATTERNS = [
    r"\bopec\b", r"\bfomc\b", r"\bnasdaq\b",
    r"\bs&p\s*500\b", r"\bus\s+treasury\b",
    r"federal\s*reserve",
]
_NUMERIC_PATTERN = re.compile(r"\b\d{1,3}(?:[.,]\d+)?\s*(?:%|조|억|만|달러|원|bp|bps)\b")
_DATE_PATTERN = re.compile(r"20\d{2}\s*[-./년]\s*\d{1,2}")
_PROPER_NOUN_HINT = re.compile(r"[A-Z][a-zA-Z]{2,}")
_TRANSCRIPT_HINT = re.compile(
    r"transcript|자막|영상|video|youtube|타임스탬프|\d{1,2}:\d{2}",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# 보조 함수
# ---------------------------------------------------------------------------
def _any_match(text: str, patterns: list[str]) -> bool:
    if not text:
        return False
    low = text.lower()
    return any(re.search(p, low) for p in patterns)


def _is_thin_query(
    *,
    source_type: str,
    source_text: str,
    source_url: Optional[str],
) -> bool:
    """topic-only 짧은 검색 요청 — RESEARCH_REQUIRED 강제."""
    if source_type not in _THIN_QUERY_SOURCE_TYPES:
        return False
    if source_url:
        return False
    body = (source_text or "").strip()
    if len(body) >= _THIN_QUERY_MIN_LEN:
        return False
    if _TRANSCRIPT_HINT.search(body):
        return False
    return True


def _detect_trust_level(factcheck_summary: str) -> str:
    """factcheck 요약에서 신뢰도 추출."""
    if not factcheck_summary:
        return LEVEL_LOW
    s = factcheck_summary.lower()
    if "검증됨" in factcheck_summary or "verified" in s:
        if "신뢰도: high" in s or "신뢰도: 높음" in factcheck_summary:
            return LEVEL_HIGH
        return LEVEL_MEDIUM
    if "미검증" in factcheck_summary or "unverified" in s:
        if "신뢰도: low" in s or "신뢰도: 낮음" in factcheck_summary:
            return LEVEL_LOW
        return LEVEL_LOW
    return LEVEL_LOW


def _detect_info_rarity(
    *,
    title: str,
    source_text: str,
    research_summary: str,
) -> str:
    """구체 숫자/고유명사/날짜 다수 → high, 일반 개념만 → low."""
    pool = " ".join([title or "", source_text or "", research_summary or ""])
    nums = len(_NUMERIC_PATTERN.findall(pool))
    dates = len(_DATE_PATTERN.findall(pool))
    proper = len(_PROPER_NOUN_HINT.findall(pool))
    score = nums * 2 + dates * 2 + min(proper, 8)
    if score >= 10:
        return LEVEL_HIGH
    if score >= 4:
        return LEVEL_MEDIUM
    return LEVEL_LOW


def _detect_reader_value(
    *,
    title: str,
    source_text: str,
    info_rarity: str,
) -> str:
    """specific entity + 시사성 → high."""
    if info_rarity == LEVEL_HIGH:
        return LEVEL_HIGH
    pool = (title or "") + " " + (source_text or "")
    if _NUMERIC_PATTERN.search(pool) and _DATE_PATTERN.search(pool):
        return LEVEL_HIGH
    if info_rarity == LEVEL_LOW and len(pool.strip()) < 300:
        return LEVEL_LOW
    return LEVEL_MEDIUM


def _detect_risk(
    *,
    title: str,
    source_text: str,
    source_url: Optional[str],
) -> tuple[str, list[str]]:
    """위험 수준 + forbidden_claims 결정."""
    pool = " ".join([title or "", source_text or "", source_url or ""])
    forbidden: list[str] = []
    risk = LEVEL_LOW

    if _any_match(pool, _BETTING_PATTERNS):
        risk = LEVEL_HIGH
        forbidden.extend([
            "베팅 권유 / 도박 권장 표현 금지",
            "확률을 '확정' 으로 단정하는 표현 금지",
            "실제 투자 / 배팅 행동 유도 금지",
        ])
    if _any_match(pool, _FINANCE_RISK_PATTERNS):
        if risk != LEVEL_HIGH:
            risk = LEVEL_HIGH
        forbidden.extend([
            "매수 / 매도 추천 표현 금지",
            "목표 주가 단정 금지",
            "수익 보장 표현 금지",
        ])
    if _any_match(pool, _KOREAN_POLITICAL_PATTERNS):
        if risk == LEVEL_LOW:
            risk = LEVEL_MEDIUM
        forbidden.extend([
            "특정 정당 / 후보 옹호 / 비판 금지",
            "정치적 단정 표현 자제",
        ])
    return risk, forbidden


def _detect_korean_context_advice(
    *,
    title: str,
    source_text: str,
) -> tuple[bool, str]:
    """
    한국 맥락 권장 여부.
    글로벌 토픽 (OPEC/FOMC/Nasdaq 등) → 한국 맥락 비권장.
    명시 한국 키워드 (한국/국내/코스피) → 한국 맥락 허용.
    """
    pool = (title or "") + " " + (source_text or "")
    has_korean_explicit = _any_match(pool, _KOREAN_EXPLICIT_PATTERNS)
    has_global_only = _any_match(pool, _GLOBAL_ONLY_PATTERNS)
    if has_korean_explicit:
        return True, "한국 맥락 허용 (명시 한국 키워드 발견)"
    if has_global_only:
        return False, "글로벌 토픽 — 한국 맥락 강제 금지"
    return False, "한국 맥락 비권장 (명시 한국 키워드 부재)"


def _detect_timing(*, title: str, source_text: str) -> str:
    """간이 신선도 — 날짜 표기 발견 여부 + breaking 표지."""
    pool = (title or "") + " " + (source_text or "")
    low = pool.lower()
    if any(k in low for k in ["속보", "breaking", "방금"]):
        return TIMING_BREAKING
    if _DATE_PATTERN.search(pool):
        return TIMING_FRESH
    return TIMING_NORMAL


def _recommend_format(
    *,
    info_rarity: str,
    risk_level: str,
    source_type: str,
    timing: str,
) -> str:
    """간이 형식 추천 (SCAN_FIRST_POST_STYLE_V1 4 후보 중 1)."""
    if risk_level == LEVEL_HIGH:
        return "DATA_LEDGER (위험 분산 — 숫자 스캔 우선)"
    if timing in (TIMING_BREAKING, TIMING_FRESH) and info_rarity == LEVEL_HIGH:
        return "WHY_MARKET_HOLDS (시장 포지션 + N 가지 이유)"
    if info_rarity == LEVEL_HIGH and source_type in ("news_link", "rss"):
        return "CURRENT_ODDS_COMPARE (판세/비교 강조)"
    if info_rarity == LEVEL_LOW:
        return "SHORT_SIGNAL (짧은 헤드라인 + 첫 댓글로 보강)"
    return "DATA_LEDGER (숫자 스캔)"


# ---------------------------------------------------------------------------
# 점수 계산
# ---------------------------------------------------------------------------
def _compute_score(
    *,
    info_rarity: str,
    trust_level: str,
    reader_value: str,
    interpretation_potential: str,
    timing: str,
    differentiation: str,
    risk_level: str,
) -> int:
    score = 50
    # trust
    if trust_level == LEVEL_HIGH:
        score += 20
    elif trust_level == LEVEL_MEDIUM:
        score += 8
    else:
        score -= 15
    # info_rarity
    if info_rarity == LEVEL_HIGH:
        score += 15
    elif info_rarity == LEVEL_MEDIUM:
        score += 4
    else:
        score -= 10
    # reader_value
    if reader_value == LEVEL_HIGH:
        score += 10
    elif reader_value == LEVEL_LOW:
        score -= 10
    # interpretation
    if interpretation_potential == LEVEL_HIGH:
        score += 5
    elif interpretation_potential == LEVEL_LOW:
        score -= 5
    # timing
    if timing == TIMING_BREAKING:
        score += 8
    elif timing == TIMING_FRESH:
        score += 4
    elif timing == TIMING_STALE:
        score -= 5
    # differentiation
    if differentiation == LEVEL_HIGH:
        score += 7
    elif differentiation == LEVEL_LOW:
        score -= 5
    # risk
    if risk_level == LEVEL_HIGH:
        score -= 12
    elif risk_level == LEVEL_MEDIUM:
        score -= 5
    return max(0, min(100, score))


def _score_to_action(score: int) -> str:
    if score >= _SCORE_PUBLISH:
        return ACTION_PUBLISH
    if score >= _SCORE_VERIFY:
        return ACTION_VERIFY_MORE
    if score >= _SCORE_COMMENT:
        return ACTION_COMMENT_ONLY
    if score >= _SCORE_RESEARCH:
        return ACTION_RESEARCH_REQUIRED
    return ACTION_DROP


# ---------------------------------------------------------------------------
# 공개 API
# ---------------------------------------------------------------------------
def evaluate_info_value(
    *,
    title: str,
    source_text: str,
    source_url: Optional[str],
    source_type: str,
    content_type: Optional[str] = None,
    research_summary: str = "",
    factcheck_summary: str = "",
) -> dict:
    """
    초안 생성 전 단계 — 정보 가치 / 신뢰 / 위험 / 한국 맥락 자동 평가.

    fail-open: 내부 예외 발생 시 보수적인 RESEARCH_REQUIRED 반환.
    """
    try:
        title = (title or "").strip()
        source_text = source_text or ""

        # Thin Query Guard ── topic-only 짧은 요청 — 강제 분기
        if _is_thin_query(
            source_type=source_type,
            source_text=source_text,
            source_url=source_url,
        ):
            risk_level, forbidden = _detect_risk(
                title=title, source_text=source_text, source_url=source_url,
            )
            korean_allowed, korean_advice = _detect_korean_context_advice(
                title=title, source_text=source_text,
            )
            return {
                "score": 35,
                "action_label": ACTION_RESEARCH_REQUIRED,
                "info_rarity": LEVEL_LOW,
                "trust_level": LEVEL_LOW,
                "reader_value": LEVEL_LOW,
                "interpretation_potential": LEVEL_LOW,
                "timing": TIMING_NORMAL,
                "differentiation": LEVEL_LOW,
                "risk_level": risk_level,
                "recommended_format": "RESEARCH_REQUIRED — 자료 부족",
                "confirmed_facts": [],
                "uncertain_parts": [
                    "소재가 짧은 키워드 / topic 만 제공됨",
                    "원문 / URL / 트랜스크립트 부재",
                ],
                "why_useful": "(자료 부족으로 판단 불가)",
                "why_risky": "구체 사실 없이 일반론 작성 시 신뢰도 저하 위험",
                "draft_input_focus": "추가 리서치 또는 원문 URL 필요",
                "korean_context_allowed": korean_allowed,
                "korean_context_advice": korean_advice,
                "forbidden_claims": forbidden + [
                    "구체 사실 없는 단정 / 추정 표현 금지",
                    "원문 미확인 상태에서 인용 금지",
                ],
                "thin_query": True,
            }

        # 표준 평가
        trust_level = _detect_trust_level(factcheck_summary)
        info_rarity = _detect_info_rarity(
            title=title,
            source_text=source_text,
            research_summary=research_summary,
        )
        reader_value = _detect_reader_value(
            title=title, source_text=source_text, info_rarity=info_rarity,
        )
        risk_level, forbidden = _detect_risk(
            title=title, source_text=source_text, source_url=source_url,
        )
        korean_allowed, korean_advice = _detect_korean_context_advice(
            title=title, source_text=source_text,
        )
        timing = _detect_timing(title=title, source_text=source_text)

        # interpretation_potential : trust 가 medium+ 이고 info_rarity high → high
        if trust_level in (LEVEL_HIGH, LEVEL_MEDIUM) and info_rarity == LEVEL_HIGH:
            interpretation_potential = LEVEL_HIGH
        elif info_rarity == LEVEL_LOW:
            interpretation_potential = LEVEL_LOW
        else:
            interpretation_potential = LEVEL_MEDIUM

        # differentiation : 영상 / 기사 등 1차 소스 → medium+
        if source_type in ("youtube", "news_link", "rss"):
            differentiation = LEVEL_HIGH if info_rarity == LEVEL_HIGH else LEVEL_MEDIUM
        else:
            differentiation = LEVEL_LOW if info_rarity == LEVEL_LOW else LEVEL_MEDIUM

        score = _compute_score(
            info_rarity=info_rarity,
            trust_level=trust_level,
            reader_value=reader_value,
            interpretation_potential=interpretation_potential,
            timing=timing,
            differentiation=differentiation,
            risk_level=risk_level,
        )
        action_label = _score_to_action(score)

        # high-risk 는 PUBLISH 차단 → 최소 VERIFY_MORE
        if risk_level == LEVEL_HIGH and action_label == ACTION_PUBLISH:
            action_label = ACTION_VERIFY_MORE

        recommended_format = _recommend_format(
            info_rarity=info_rarity,
            risk_level=risk_level,
            source_type=source_type,
            timing=timing,
        )

        # confirmed_facts / uncertain_parts — research_summary 한 줄 요약 그대로
        confirmed_facts: list[str] = []
        uncertain_parts: list[str] = []
        if research_summary:
            head = research_summary.strip().splitlines()[0][:150]
            if head:
                confirmed_facts.append(head)
        if trust_level == LEVEL_LOW:
            uncertain_parts.append("팩트체크 미검증 또는 신뢰도 낮음")
        if info_rarity == LEVEL_LOW:
            uncertain_parts.append("구체 숫자 / 날짜 / 고유명사 부족")

        why_useful = (
            f"info_rarity={info_rarity} / reader_value={reader_value} / "
            f"timing={timing}"
        )
        why_risky = (
            f"risk={risk_level} / trust={trust_level}"
            + (" / 한국 맥락 강제 금지" if not korean_allowed else "")
        )
        draft_input_focus = (
            f"{action_label} 권장 — recommended_format={recommended_format}"
        )

        return {
            "score": score,
            "action_label": action_label,
            "info_rarity": info_rarity,
            "trust_level": trust_level,
            "reader_value": reader_value,
            "interpretation_potential": interpretation_potential,
            "timing": timing,
            "differentiation": differentiation,
            "risk_level": risk_level,
            "recommended_format": recommended_format,
            "confirmed_facts": confirmed_facts,
            "uncertain_parts": uncertain_parts,
            "why_useful": why_useful,
            "why_risky": why_risky,
            "draft_input_focus": draft_input_focus,
            "korean_context_allowed": korean_allowed,
            "korean_context_advice": korean_advice,
            "forbidden_claims": forbidden,
            "thin_query": False,
        }

    except Exception as e:
        logger.warning(f"[info-value-gate] 평가 실패 (fail-open): {e}")
        return {
            "score": 40,
            "action_label": ACTION_RESEARCH_REQUIRED,
            "info_rarity": LEVEL_LOW,
            "trust_level": LEVEL_LOW,
            "reader_value": LEVEL_LOW,
            "interpretation_potential": LEVEL_LOW,
            "timing": TIMING_NORMAL,
            "differentiation": LEVEL_LOW,
            "risk_level": LEVEL_MEDIUM,
            "recommended_format": "RESEARCH_REQUIRED — 평가 실패",
            "confirmed_facts": [],
            "uncertain_parts": ["info-value gate 평가 실패"],
            "why_useful": "(평가 실패)",
            "why_risky": "평가 실패 — 보수 분기",
            "draft_input_focus": "추가 자료 확보 후 재평가",
            "korean_context_allowed": False,
            "korean_context_advice": "평가 실패 — 한국 맥락 비권장",
            "forbidden_claims": ["평가 실패 — 단정 표현 금지"],
            "thin_query": False,
        }


# ---------------------------------------------------------------------------
# 텔레그램 카드용 4-6 줄 블록 포매터
# ---------------------------------------------------------------------------
def format_info_value_block(eval_result: dict) -> str:
    """
    분석 카드에 추가할 4-6 줄 블록.
    HTML 안전 (<b>, <i> 외 태그 미사용).
    """
    try:
        score = eval_result.get("score", 0)
        action = eval_result.get("action_label", "RESEARCH_REQUIRED")
        rarity = eval_result.get("info_rarity", "low")
        trust = eval_result.get("trust_level", "low")
        risk = eval_result.get("risk_level", "low")
        rec_fmt = eval_result.get("recommended_format", "-")
        forbidden = eval_result.get("forbidden_claims", [])

        action_emoji = {
            ACTION_PUBLISH: "🟢",
            ACTION_VERIFY_MORE: "🟡",
            ACTION_COMMENT_ONLY: "💬",
            ACTION_RESEARCH_REQUIRED: "🔎",
            ACTION_DROP: "🛑",
        }.get(action, "🔎")

        lines = [
            f"{action_emoji} <b>정보 가치 게이트</b>: {score}/100 → <b>{action}</b>",
            f"  • 희소성={rarity} / 신뢰={trust} / 위험={risk}",
            f"  • 추천 형식: {rec_fmt}",
        ]
        if forbidden:
            head = forbidden[0]
            extra = f" 외 {len(forbidden)-1}건" if len(forbidden) > 1 else ""
            lines.append(f"  • 금지: {head}{extra}")
        return "\n".join(lines)
    except Exception:
        return ""
