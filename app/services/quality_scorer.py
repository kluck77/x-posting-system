"""
초안 퀄리티 스코어러
====================
AI가 생성한 초안을 자동으로 채점하고, 기준 미달 시 재생성을 요청합니다.

채점 기준 (총 100점):
  +20  훅에 숫자/퍼센트/배수가 있음
  +20  첫 줄이 "South Korea" / "Korea's" 로 시작하지 않음
  +15  CTA 포함 (Follow / Bookmark / Thread 등)
  +15  본문 270자 이하
  +10  "you" 직접 호칭 포함
  +10  구체적 국가/기관/인물명 포함 (맥락 구체성)
  +10  커뮤니티 입력 시 감정/반응 표현 포함
  -15  금지어 포함 (however, furthermore, it is worth noting 등)
  -10  본문 270자 초과할 때마다

임계값: 60점 미만 → 자동 재생성 (최대 2회)
"""

import re
import logging
from app.providers.base import DraftResult

logger = logging.getLogger(__name__)

# 금지어 (패턴)
_BANNED = [
    r"\bhowever\b",
    r"\bfurthermore\b",
    r"\bmoreover\b",
    r"\bit is worth noting\b",
    r"\bit should be noted\b",
    r"\bin conclusion\b",
    r"\bto summarize\b",
    r"\bnotably\b",
]

# CTA 패턴
_CTA_PATTERNS = [
    r"\bfollow\b",
    r"\bbookmark\b",
    r"\bthread\b",
    r"\bkeep.{0,10}(watch|track|eye)",
]

# 숫자/지표 패턴
_NUMBER_PATTERN = re.compile(
    r"(\d+[.,]?\d*\s*(%|억|조|만|원|달러|won|usd|btc|x|\+|-|bp|bps|'s))|"
    r"(\$[\d,]+)|"
    r"(\d+\.\d+)|"
    r"(#\d+)",
    re.IGNORECASE,
)

# 감정/반응 표현 (커뮤니티 입력용)
_SENTIMENT_PATTERN = re.compile(
    r"\b(panic|fear|angry|concern|worry|bullish|bearish|react|surge|crash|dump|pump|"
    r"panicck|skeptic|optimis|pessimis)\w*\b",
    re.IGNORECASE,
)

REGEN_THRESHOLD = 60  # 이 점수 미만이면 재생성 요청


def score_draft(draft: DraftResult, source_type: str = "manual") -> tuple[int, list[str]]:
    """
    초안을 채점하고 (점수, 이유 목록)을 반환합니다.

    Args:
        draft: 채점할 초안
        source_type: "manual" 또는 "community_input"

    Returns:
        (score: int, reasons: list[str])
    """
    score = 0
    reasons: list[str] = []
    full = f"{draft.hook}\n{draft.body}"
    hook_lower = draft.hook.lower()
    body_lower = draft.body.lower()
    full_lower  = full.lower()

    # +20 훅에 숫자 포함
    if _NUMBER_PATTERN.search(draft.hook):
        score += 20
        reasons.append("+20 훅에 숫자/지표 있음")
    else:
        reasons.append(" 0 훅에 숫자 없음 (필수)")

    # +20 금지 시작어 없음
    bad_starts = ("south korea", "korea's", "in south korea", "south korea's")
    if not any(hook_lower.startswith(s) for s in bad_starts):
        score += 20
        reasons.append("+20 훅 시작어 OK")
    else:
        reasons.append("-0 훅이 'South Korea'/'Korea's'로 시작 (감점 없으나 약점)")

    # +15 CTA 포함
    if any(re.search(p, full_lower) for p in _CTA_PATTERNS):
        score += 15
        reasons.append("+15 CTA 포함")
    else:
        reasons.append(" 0 CTA 없음")

    # +15 본문 270자 이하
    body_len = len(draft.body)
    if body_len <= 270:
        score += 15
        reasons.append(f"+15 본문 {body_len}자 (270 이하)")
    else:
        penalty = min(30, ((body_len - 270) // 30) * 10)
        score -= penalty
        reasons.append(f"-{penalty} 본문 {body_len}자 초과")

    # +10 "you" 직접 호칭
    if re.search(r"\byou\b|\byour\b", full_lower):
        score += 10
        reasons.append("+10 'you' 직접 호칭")
    else:
        reasons.append(" 0 'you' 없음")

    # +10 구체적 맥락 (기관명/지명/통화/수치)
    context_pattern = re.compile(
        r"\b(korea|korean|seoul|won|krw|bok|samsung|hyundai|sk|lg|kospi|"
        r"bitcoin|ethereum|btc|eth|binance|upbit|bithumb)\b",
        re.IGNORECASE,
    )
    if context_pattern.search(full):
        score += 10
        reasons.append("+10 구체적 맥락(기관/통화) 포함")
    else:
        reasons.append(" 0 구체적 맥락 없음")

    # +10 커뮤니티 입력 시 감정 표현
    if source_type == "community_input":
        if _SENTIMENT_PATTERN.search(full):
            score += 10
            reasons.append("+10 커뮤 감정/반응 표현 포함")
        else:
            reasons.append(" 0 커뮤 감정 표현 없음")
    else:
        score += 10  # 일반 입력은 이 항목 면제
        reasons.append("+10 일반 입력 (감정 표현 항목 면제)")

    # -15 금지어
    for pattern in _BANNED:
        if re.search(pattern, full_lower):
            score -= 15
            reasons.append(f"-15 금지어: '{pattern}'")

    score = max(0, min(100, score))
    return score, reasons


def should_regenerate(score: int) -> bool:
    """점수가 임계값 미만이면 재생성 필요."""
    return score < REGEN_THRESHOLD


def format_score_report(score: int, reasons: list[str]) -> str:
    """점수 리포트 텍스트 반환 (로그/Telegram용)."""
    grade = "✅ 통과" if score >= REGEN_THRESHOLD else "⚠️ 재생성 필요"
    lines = [f"📊 품질 점수: {score}/100 {grade}"] + reasons
    return "\n".join(lines)


# ─── 스레드 품질 채점 ─────────────────────────────────────────────────────────

THREAD_REGEN_THRESHOLD = 55  # 스레드는 기준을 약간 낮게 (트윗이 많아 평균 편차)


def score_thread(tweets: list[str]) -> tuple[int, list[str]]:
    """
    트위터 스레드 전체를 채점합니다.

    채점 기준:
      +20  첫 트윗(훅)에 숫자 포함
      +20  첫 트윗이 금지 시작어로 시작하지 않음
      +15  마지막 트윗에 CTA 포함
      +15  모든 트윗이 270자 이하
      +10  "you/your" 직접 호칭 (스레드 전체에서)
      +10  한국 관련 구체적 맥락 포함
      +10  4번째 트윗에 커뮤니티/포럼 언급
      -15  금지어 포함 (전체)
      -5   270자 초과 트윗당

    Returns:
        (score: int, reasons: list[str])
    """
    if not tweets:
        return 0, ["스레드 트윗 없음"]

    score = 0
    reasons: list[str] = []
    hook = tweets[0]
    last = tweets[-1]
    all_text = "\n".join(tweets).lower()
    hook_lower = hook.lower()

    # +20 첫 트윗에 숫자
    if _NUMBER_PATTERN.search(hook):
        score += 20
        reasons.append("+20 훅(1번 트윗)에 숫자/지표 있음")
    else:
        reasons.append(" 0 훅에 숫자 없음")

    # +20 금지 시작어 없음
    bad_starts = ("south korea", "korea's", "in south korea", "south korea's")
    if not any(hook_lower.startswith(s) for s in bad_starts):
        score += 20
        reasons.append("+20 훅 시작어 OK")
    else:
        reasons.append(" 0 훅이 금지 시작어로 시작")

    # +15 마지막 트윗에 CTA
    if any(re.search(p, last.lower()) for p in _CTA_PATTERNS):
        score += 15
        reasons.append("+15 마지막 트윗에 CTA 있음")
    else:
        reasons.append(" 0 마지막 트윗 CTA 없음")

    # +15 모든 트윗 270자 이하
    over_limit = [i + 1 for i, t in enumerate(tweets) if len(t) > 270]
    if not over_limit:
        score += 15
        reasons.append("+15 모든 트윗 270자 이하")
    else:
        penalty = len(over_limit) * 5
        score -= penalty
        reasons.append(f"-{penalty} 트윗 {over_limit} 270자 초과")

    # +10 "you" 호칭
    if re.search(r"\byou\b|\byour\b", all_text):
        score += 10
        reasons.append("+10 'you' 직접 호칭")
    else:
        reasons.append(" 0 'you' 없음")

    # +10 구체적 맥락
    context_pattern = re.compile(
        r"\b(korea|korean|seoul|won|krw|bok|samsung|hyundai|sk|lg|kospi|"
        r"bitcoin|ethereum|btc|eth|binance|upbit|bithumb)\b",
        re.IGNORECASE,
    )
    if context_pattern.search("\n".join(tweets)):
        score += 10
        reasons.append("+10 구체적 맥락 포함")
    else:
        reasons.append(" 0 구체적 맥락 없음")

    # +10 4번째 트윗에 커뮤니티 언급 (있을 때)
    if len(tweets) >= 4:
        forum_pattern = re.compile(
            r"\b(forum|community|dcinside|fmkorea|reddit|korean.{0,10}say|reaction|sentiment)\b",
            re.IGNORECASE,
        )
        if forum_pattern.search(tweets[3]):
            score += 10
            reasons.append("+10 4번째 트윗에 커뮤니티 반응 언급")
        else:
            reasons.append(" 0 4번째 트윗 커뮤니티 언급 없음")

    # -15 금지어 (전체 스레드)
    for pattern in _BANNED:
        if re.search(pattern, all_text):
            score -= 15
            reasons.append(f"-15 금지어: '{pattern}'")

    score = max(0, min(100, score))
    return score, reasons


def should_regenerate_thread(score: int) -> bool:
    """스레드 점수가 임계값 미만이면 재생성 필요."""
    return score < THREAD_REGEN_THRESHOLD


# =============================================================================
# 5-CRITERIA 품질 필터
# =============================================================================

# 해석 신호 (단순 번역이 아닌 관점 제시 증거)
_INTERPRETATION_SIGNALS = re.compile(
    r"\b(means|signals|explains|because|structural|mechanism|pattern|"
    r"what this (tells|shows|reveals)|the real (reason|issue|story)|"
    r"beneath|underneath|what (nobody|most) (says|knows|covers))\b",
    re.IGNORECASE,
)

# 시장성 신호 (해외 독자 관련성)
_MARKETABILITY_SIGNALS = re.compile(
    r"\b(global|supply chain|usd|dollar|semiconductor|chip|crypto|bitcoin|"
    r"geopolit|trade|export|import|market|investor|hedge fund|wall street|"
    r"your (wallet|portfolio|iphone|investment))\b",
    re.IGNORECASE,
)

# 반복 방문 신호
_REPEAT_SIGNALS = re.compile(
    r"\b(watch|track|follow|developing|pattern|series|next week|by (friday|monday)|"
    r"this is part of|will continue|won't stop|over the (next|coming))\b",
    re.IGNORECASE,
)

# 잘못된 청중 신호 (엔터테인먼트, 클릭베이트)
_WRONG_AUDIENCE_SIGNALS = re.compile(
    r"\b(shocking|unbelievable|can't believe|omg|insane|crazy|viral|drama|"
    r"celebrity|idol|dating|scandal|rumors|gossip)\b",
    re.IGNORECASE,
)

# 단순 번역 패턴 (Reuters 그대로 옮기는 패턴)
_TRANSLATION_PATTERNS = re.compile(
    r"^(south korea|korea) (announced|said|reported|stated|confirmed|revealed)\b",
    re.IGNORECASE,
)


def score_5criteria(hook: str, body: str, source_type: str = "manual") -> dict:
    """
    5-criteria 프레임워크로 초안을 평가합니다.

    반환값:
    {
        "scores": {"expertise": int, "marketability": int, ...},  # 각 0~20
        "total": int,       # 0~100
        "flags": [str],     # 실패/약점 항목 설명
        "action": "pass"|"warn"|"reject"
    }

    임계값:
        total >= 70  → pass
        total 50~69  → warn (검토 필요)
        total < 50   → reject (재생성)
    """
    full = f"{hook}\n{body}"
    full_lower = full.lower()
    flags: list[str] = []
    scores: dict[str, int] = {}

    # ── 1. Expertise (해석 vs 번역) ──────────────────────────────────────────
    exp_score = 0
    if _INTERPRETATION_SIGNALS.search(full):
        exp_score += 15
    if not _TRANSLATION_PATTERNS.search(hook):
        exp_score += 5
    scores["expertise"] = min(exp_score, 20)
    if exp_score < 10:
        flags.append("⚠️ Expertise WEAK: 해석/관점 없음. 단순 번역 의심.")

    # ── 2. Marketability (해외 독자 관련성) ─────────────────────────────────
    mkt_score = 0
    if _MARKETABILITY_SIGNALS.search(full):
        mkt_score += 20
    elif re.search(r"\b(korea|korean|seoul|won|kospi)\b", full_lower):
        mkt_score += 8  # 한국 언급은 있지만 글로벌 연결 없음
    scores["marketability"] = min(mkt_score, 20)
    if mkt_score < 10:
        flags.append("⚠️ Marketability WEAK: 해외 독자 관련성 불명확.")

    # ── 3. Consistency (브랜드 일관성) ──────────────────────────────────────
    con_score = 20
    if _WRONG_AUDIENCE_SIGNALS.search(full):
        con_score -= 15
        flags.append("❌ Consistency FAIL: 클릭베이트/엔터테인먼트 신호 감지.")
    pillar_pattern = re.compile(
        r"\b(economy|crypto|geopolit|policy|community|finance|trade|politic)\w*\b",
        re.IGNORECASE,
    )
    if not pillar_pattern.search(full):
        con_score -= 5
        flags.append("⚠️ Consistency WEAK: 4개 필러 중 어느 것도 명확하지 않음.")
    scores["consistency"] = max(0, con_score)

    # ── 4. Follower Quality (적합한 팔로워 유인) ─────────────────────────────
    fq_score = 0
    right_audience = re.compile(
        r"\b(investor|analyst|market|hedge|fund|trader|researcher|"
        r"economist|policy|analyst|strategist)\b",
        re.IGNORECASE,
    )
    if right_audience.search(full):
        fq_score += 10
    if _MARKETABILITY_SIGNALS.search(full):
        fq_score += 5
    if re.search(r"\byou\b|\byour\b", full_lower):
        fq_score += 5
    scores["follower_quality"] = min(fq_score, 20)
    if fq_score < 10:
        flags.append("⚠️ Follower Quality WEAK: 정보 지향 독자를 구체적으로 겨냥하지 않음.")

    # ── 5. Repeat Consumption (재방문 유인) ──────────────────────────────────
    rc_score = 0
    if _REPEAT_SIGNALS.search(full):
        rc_score += 20
    elif re.search(r"\bfollow\b", full_lower):
        rc_score += 10  # CTA는 있지만 패턴/시리즈 신호 없음
    scores["repeat_consumption"] = min(rc_score, 20)
    if rc_score < 10:
        flags.append("⚠️ Repeat Consumption WEAK: 재방문 유인 신호(패턴/시리즈/추적) 없음.")

    total = sum(scores.values())

    if total >= 70:
        action = "pass"
    elif total >= 50:
        action = "warn"
    else:
        action = "reject"

    return {
        "scores": scores,
        "total": total,
        "flags": flags,
        "action": action,
    }


def format_5criteria_report(result: dict) -> str:
    """5-criteria 결과를 Telegram용 텍스트로 포맷합니다."""
    icons = {"pass": "✅", "warn": "⚠️", "reject": "❌"}
    icon = icons.get(result["action"], "❓")
    lines = [
        f"🔬 5-Criteria 품질 분석: {result['total']}/100 {icon}",
        f"  전문성(해석): {result['scores']['expertise']}/20",
        f"  시장성(관련성): {result['scores']['marketability']}/20",
        f"  일관성(브랜드): {result['scores']['consistency']}/20",
        f"  팔로워 적합성: {result['scores']['follower_quality']}/20",
        f"  재방문 유인: {result['scores']['repeat_consumption']}/20",
    ]
    if result["flags"]:
        lines.append("")
        lines.extend(result["flags"])
    return "\n".join(lines)
