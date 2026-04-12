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

# ─── 한국어 5-criteria 신호 패턴 ─────────────────────────────────────────────
# 배경: 위 영어 regex 는 전부 `\b` word boundary 를 사용한다. Python `re` 의 `\b`
# 는 ASCII word character 기준이라 한국어 글자 경계에서는 동작이 보장되지 않고,
# 결과적으로 한국어 Reviewer 출력은 expertise/marketability/follower_quality/
# repeat_consumption 에서 전부 0 점에 수렴해 total=20 근처로 고정됐다 (실관측).
# 그래서 한국어 본문은 품질과 무관하게 무조건 reject 로 떨어져 "한국어 기본"
# 운영 정책과 충돌했다.
#
# 해결: 기존 영어 regex 는 손대지 않는다. 대신 `\b` 없는 substring 매치용
# 한국어 패턴을 모듈 레벨에 별도로 두고, score_5criteria 내부에서 OR 결합만
# 한다. 이렇게 하면:
#   1) 영어 본문 점수/판정은 완전히 보존된다 (기존 회귀 동일).
#   2) 한국어 본문도 해석/글로벌/팔로워/재방문 신호가 실제 있으면 점수가 오른다.
#   3) 해석 없는 단순 요약 한국어 본문은 여전히 낮은 점수를 받는다 (억지 인플 없음).
#
# 주의: 한국어 regex 에 `\b` 를 쓰면 안 된다 (substring 매치가 의도).

_INTERPRETATION_SIGNALS_KO = re.compile(
    r"때문에|때문|의미|의미하는|의미는|배경|핵심은|핵심 배경|핵심 이유|"
    r"사실상|구조적|구조는|본질|본질적|진짜 이유|진짜 원인|원인은|"
    r"주목할|주목해야|보여준다|보여주는|드러난|드러내|"
    r"시사한다|시사하는|시사점|결국|결과적으로"
)

_MARKETABILITY_SIGNALS_KO = re.compile(
    r"글로벌|해외|국제|달러|원달러|환율|공급망|밸류체인|반도체|배터리|"
    r"지정학|지경학|외국인|외국계|자본유출|자본유입|자금흐름|"
    r"연준|FOMC|월가|수출|수입|무역|원화|유가|원유|국채|"
    r"미국|중국|일본|유럽|대만|인도"
)

_REPEAT_SIGNALS_KO = re.compile(
    r"추적|추적해야|관찰|관찰해야|지켜봐야|주시해야|주의 깊게|"
    r"패턴|반복|후속|이어서|계속|향후|앞으로|"
    r"다음 주|다음주|이번 주|이번주|다음 달|이번 달|매주|매일|"
    r"시리즈|연속적|다음 편|이 흐름|이 추세"
)

_WRONG_AUDIENCE_SIGNALS_KO = re.compile(
    r"충격|대박|소름|난리|품절대란|열풍|"
    r"스캔들|열애|루머|가십|파경|결별|"
    r"실화|레전드|짜릿|헉|쇼킹"
)

# Consistency — 4-pillar 필러 한국어
_PILLAR_SIGNALS_KO = re.compile(
    r"경제|거시|경기|금리|통화정책|가계부채|환율|국채|채권|"
    r"크립토|암호화폐|비트코인|이더리움|코인|"
    r"정책|규제|지정학|정치|외교|"
    r"금융|은행|증권|펀드|"
    r"무역|수출|수입|공급망|"
    r"커뮤니티|산업|반도체|배터리|조선|"
    r"증시|주식|코스피|코스닥|부동산|주택"
)

# Follower quality — 정보 지향 독자 유인 한국어
_RIGHT_AUDIENCE_SIGNALS_KO = re.compile(
    r"투자자|개인 투자자|기관 투자자|분석가|애널리스트|"
    r"트레이더|전략가|리서치|연구원|이코노미스트|"
    r"헤지펀드|정책입안자|시장 참여자"
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
    if _INTERPRETATION_SIGNALS.search(full) or _INTERPRETATION_SIGNALS_KO.search(full):
        exp_score += 15
    if not _TRANSLATION_PATTERNS.search(hook):
        exp_score += 5
    scores["expertise"] = min(exp_score, 20)
    if exp_score < 10:
        flags.append("⚠️ Expertise WEAK: 해석/관점 없음. 단순 번역 의심.")

    # ── 2. Marketability (해외 독자 관련성) ─────────────────────────────────
    mkt_score = 0
    has_mkt_signal = (
        _MARKETABILITY_SIGNALS.search(full) is not None
        or _MARKETABILITY_SIGNALS_KO.search(full) is not None
    )
    if has_mkt_signal:
        mkt_score += 20
    elif (
        re.search(r"\b(korea|korean|seoul|won|kospi)\b", full_lower)
        or re.search(r"한국|서울|원화|코스피|코스닥", full)
    ):
        mkt_score += 8  # 한국 언급은 있지만 글로벌 연결 없음
    scores["marketability"] = min(mkt_score, 20)
    if mkt_score < 10:
        flags.append("⚠️ Marketability WEAK: 해외 독자 관련성 불명확.")

    # ── 3. Consistency (브랜드 일관성) ──────────────────────────────────────
    con_score = 20
    if _WRONG_AUDIENCE_SIGNALS.search(full) or _WRONG_AUDIENCE_SIGNALS_KO.search(full):
        con_score -= 15
        flags.append("❌ Consistency FAIL: 클릭베이트/엔터테인먼트 신호 감지.")
    pillar_pattern = re.compile(
        r"\b(economy|crypto|geopolit|policy|community|finance|trade|politic)\w*\b",
        re.IGNORECASE,
    )
    if not (pillar_pattern.search(full) or _PILLAR_SIGNALS_KO.search(full)):
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
    if right_audience.search(full) or _RIGHT_AUDIENCE_SIGNALS_KO.search(full):
        fq_score += 10
    if has_mkt_signal:
        fq_score += 5
    if re.search(r"\byou\b|\byour\b", full_lower):
        fq_score += 5
    scores["follower_quality"] = min(fq_score, 20)
    if fq_score < 10:
        flags.append("⚠️ Follower Quality WEAK: 정보 지향 독자를 구체적으로 겨냥하지 않음.")

    # ── 5. Repeat Consumption (재방문 유인) ──────────────────────────────────
    rc_score = 0
    if _REPEAT_SIGNALS.search(full) or _REPEAT_SIGNALS_KO.search(full):
        rc_score += 20
    elif re.search(r"\bfollow\b", full_lower) or re.search(r"팔로우|구독", full):
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
