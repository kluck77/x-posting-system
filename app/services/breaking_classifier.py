"""
BREAKING ALERT CLASSIFIER
=========================
네이버 기사 입력 1건을 BREAKING_NOW / CANDIDATE / HOLD / REJECT 로 분류하는
규칙 기반 분류기. 본 모듈은 1단계 구현(분류까지)만 책임진다.

1단계 범위
- 외부 API 호출 / DB 접근 / 캐시 / 스케줄러 / 텔레그램 발송 일체 금지
- 점수식(TOP5) 선반영 금지 — 본 모듈은 라벨링만
- 모든 규칙은 순수 함수 + 하드코딩 키워드 사전 기반

참고 문서 (구현 기준 우선순위 순)
- docs/TELEGRAM_BREAKING_ALERT_TEMPLATE.md  — BREAKING_NOW 예시 / 제외 규칙
- docs/ACCOUNT_CONSTITUTION.md §1.2, §2      — 4개 도메인 / 비허용 범위
- (참고 예정) docs/BREAKING_ALERT_FILTER_SPEC.md — 현재 레포에 미존재, 세션 지시서의
  최소 요구 항목을 본 모듈의 기준선으로 사용
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Optional

Classification = Literal["BREAKING_NOW", "CANDIDATE", "HOLD", "REJECT"]
TopicDomain = Literal["금융", "투자", "크립토", "주식", "정치", "none"]
Urgency = Literal["high", "medium"]


# ---------------------------------------------------------------------------
# 도메인 키워드 사전 (1단계 하드코딩)
# ---------------------------------------------------------------------------
# STRONG  : 해당 도메인 정면 진입 신호. 1개라도 매칭되면 해당 도메인으로 판정.
# SUPPORT : 보조 신호. STRONG 없이 SUPPORT 만 매칭되면 "인접 매칭" → CANDIDATE 로만
# EXCLUDE : 계정 범위 밖 키워드. 1개라도 매칭되면 REJECT.

STRONG_KEYWORDS: dict[str, list[str]] = {
    "금융": [
        "기준금리", "정책금리", "금통위", "한은", "한국은행",
        "금리 인하", "금리 인상", "빅스텝", "스몰컷",
        "환율", "원/달러", "외환보유",
        "FOMC", "연준", "파월",
        "가계부채", "국고채",
    ],
    "투자": [
        "자금 유입", "자금 유출", "순유입", "순유출",
        "리밸런싱", "자산배분",
        "ETF 유입", "펀드 환매",
        "기관 매수", "기관 매도",
    ],
    "크립토": [
        "비트코인", "이더리움", "BTC", "ETH",
        "거래소", "업비트", "빗썸", "바이낸스", "코인베이스",
        "ETF 승인", "ETF 거부", "현물 ETF",
        "SEC", "스테이블코인",
        "해킹", "온체인",
    ],
    "주식": [
        "코스피", "코스닥", "KOSPI", "KOSDAQ",
        "외국인 매수", "외국인 매도", "연기금",
        "어닝 서프라이즈", "실적 경고", "실적 발표",
        "상장폐지", "서킷브레이커", "거래정지",
        "삼성전자", "SK하이닉스",
    ],
    "정치": [
        "대통령", "지지율", "국정운영",
        "국회", "여당", "야당", "국무회의",
        "탄핵", "계엄", "비상",
        "총선", "대선", "선거", "여론조사",
        "국무총리", "대통령실",
    ],
}

SUPPORT_KEYWORDS: dict[str, list[str]] = {
    "금융": ["금리", "환율", "물가", "인플레이션"],
    "투자": ["자금", "포트폴리오", "헤지"],
    "크립토": ["가상자산", "디지털자산", "블록체인", "알트코인"],
    "주식": ["종목", "수급", "시가총액", "배당"],
    "정치": ["정당", "의원", "장관", "민생", "정책"],
}

EXCLUDE_KEYWORDS: list[str] = [
    "K-pop", "KPOP", "kpop", "아이돌", "드라마",
    "연예", "가수", "배우", "열애",
    "예능", "영화 리뷰", "라이프스타일",
    "프로야구", "축구 국가대표", "KBO 리그",
]

# BREAKING 이벤트 신호 (STRONG 과 조합되었을 때만 BREAKING_NOW 로 승격)
# 각 tuple = (탐지 키워드, 사유 라벨)
BREAKING_HIGH_SIGNALS: list[tuple[str, str]] = [
    ("인하 의결", "정책 결정"),
    ("인상 의결", "정책 결정"),
    ("의결", "정책 결정"),
    ("승인", "규제 결정"),
    ("거부", "규제 결정"),
    ("중단", "시장 사고"),
    ("정지", "시장 사고"),
    ("해킹", "보안 사고"),
    ("서킷브레이커", "시장 충격"),
    ("거래정지", "시장 충격"),
]

BREAKING_MEDIUM_SIGNALS: list[tuple[str, str]] = [
    ("장중 급락", "가격 충격"),
    ("장중 급등", "가격 충격"),
    ("돌파", "가격 충격"),
    ("사상 최대", "규모 충격"),
    ("사상 최저", "규모 충격"),
    ("신규 승인", "규제 결정"),
]

# 본문 최소 길이 (HOLD 가드)
MIN_BODY_CHARS = 80
MIN_BODY_SENTENCES = 3

# BREAKING 승격 최소 본문 길이 (보수적 — TEMPLATE §10.2 참고)
BREAKING_MIN_BODY_CHARS = 150


@dataclass
class ClassificationResult:
    classification: Classification
    topic_domain: TopicDomain
    matched_keywords: list[str] = field(default_factory=list)
    breaking_reason: Optional[str] = None
    urgency: Optional[Urgency] = None


def classify_article(
    *,
    title: str,
    body: str,
    publisher: Optional[str] = None,
    published_at: Optional[datetime] = None,
    url: Optional[str] = None,
) -> ClassificationResult:
    """
    기사 1건을 BREAKING_NOW / CANDIDATE / HOLD / REJECT 로 분류한다.

    판정 순서 (위에서부터, 짧은 회로) :
    1. 본문이 짧거나 3문장 미만        → HOLD
    2. URL 누락                         → HOLD
    3. EXCLUDE 키워드 매칭              → REJECT
    4. 도메인 매칭 없음                 → REJECT
    5. STRONG 없이 SUPPORT 만 매칭      → CANDIDATE (약한 후보)
    6. STRONG 매칭 + BREAKING 신호 +
       본문 BREAKING_MIN_BODY_CHARS 이상 → BREAKING_NOW
    7. 그 외 STRONG 매칭                → CANDIDATE

    publisher / published_at 는 1단계에서는 사용하지 않지만,
    향후 dedup / 신선도 산정에서 사용할 것이므로 시그니처에만 포함한다.
    """
    _ = publisher, published_at  # 1단계 미사용, 시그니처만 유지

    title_s = (title or "").strip()
    body_s = (body or "").strip()
    combined = f"{title_s}\n{body_s}"
    lowered = combined.lower()

    # 1) 본문 빈약 → HOLD (단, 제목에 STRONG 키워드 있으면 CANDIDATE 구제)
    if len(body_s) < MIN_BODY_CHARS or _count_sentences(body_s) < MIN_BODY_SENTENCES:
        excluded = _match_any(combined, lowered, EXCLUDE_KEYWORDS)
        if not excluded:
            title_strong = _match_domains(title_s, title_s.lower(), STRONG_KEYWORDS)
            if title_strong:
                primary_domain, kws = _pick_primary(title_strong)
                return ClassificationResult(
                    classification="CANDIDATE",
                    topic_domain=primary_domain,
                    matched_keywords=kws[:5],
                )
        return ClassificationResult(
            classification="HOLD",
            topic_domain="none",
        )

    # 2) URL 누락 → HOLD
    if not url or not url.strip():
        return ClassificationResult(
            classification="HOLD",
            topic_domain="none",
        )

    # 3) 제외 키워드 → REJECT
    excluded = _match_any(combined, lowered, EXCLUDE_KEYWORDS)
    if excluded:
        return ClassificationResult(
            classification="REJECT",
            topic_domain="none",
            matched_keywords=excluded[:5],
        )

    # 4) 도메인 매칭
    strong_matches = _match_domains(combined, lowered, STRONG_KEYWORDS)
    support_matches = _match_domains(combined, lowered, SUPPORT_KEYWORDS)

    if not strong_matches and not support_matches:
        return ClassificationResult(
            classification="REJECT",
            topic_domain="none",
        )

    # 5) STRONG 없이 SUPPORT 만 → CANDIDATE
    if not strong_matches:
        primary_domain, kws = _pick_primary(support_matches)
        return ClassificationResult(
            classification="CANDIDATE",
            topic_domain=primary_domain,
            matched_keywords=kws[:5],
        )

    primary_domain, strong_kws = _pick_primary(strong_matches)

    # 6) BREAKING 승격 여부 (보수적)
    if len(body_s) >= BREAKING_MIN_BODY_CHARS:
        high = _find_breaking_signal(combined, BREAKING_HIGH_SIGNALS)
        if high:
            keyword, reason_label = high
            return ClassificationResult(
                classification="BREAKING_NOW",
                topic_domain=primary_domain,
                matched_keywords=strong_kws[:5],
                breaking_reason=f"{reason_label} ({keyword})",
                urgency="high",
            )
        medium = _find_breaking_signal(combined, BREAKING_MEDIUM_SIGNALS)
        if medium:
            keyword, reason_label = medium
            return ClassificationResult(
                classification="BREAKING_NOW",
                topic_domain=primary_domain,
                matched_keywords=strong_kws[:5],
                breaking_reason=f"{reason_label} ({keyword})",
                urgency="medium",
            )

    # 7) STRONG 매칭은 있으나 BREAKING 신호 없음 → CANDIDATE
    return ClassificationResult(
        classification="CANDIDATE",
        topic_domain=primary_domain,
        matched_keywords=strong_kws[:5],
    )


# ---------------------------------------------------------------------------
# 내부 유틸 (순수 함수)
# ---------------------------------------------------------------------------
def _count_sentences(text: str) -> int:
    if not text:
        return 0
    parts = re.split(r"[.!?。]|\n+", text)
    return sum(1 for p in parts if p.strip())


def _match_any(combined: str, lowered: str, keywords: list[str]) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for kw in keywords:
        if not kw:
            continue
        if kw in seen:
            continue
        if kw in combined or kw.lower() in lowered:
            found.append(kw)
            seen.add(kw)
    return found


def _match_domains(
    combined: str,
    lowered: str,
    table: dict[str, list[str]],
) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for domain, keywords in table.items():
        matched = _match_any(combined, lowered, keywords)
        if matched:
            result[domain] = matched
    return result


_DOMAIN_PRIORITY = ["금융", "정치", "투자", "크립토", "주식"]


def _pick_primary(matches: dict[str, list[str]]) -> tuple[TopicDomain, list[str]]:
    # 매칭 개수 많은 쪽 우선. 동률이면 _DOMAIN_PRIORITY 순서 우선.
    best_domain = max(
        matches.keys(),
        key=lambda d: (len(matches[d]), -_DOMAIN_PRIORITY.index(d)),
    )
    return best_domain, matches[best_domain]  # type: ignore[return-value]


def _find_breaking_signal(
    text: str,
    signal_table: list[tuple[str, str]],
) -> Optional[tuple[str, str]]:
    for keyword, reason_label in signal_table:
        if keyword in text:
            return (keyword, reason_label)
    return None
