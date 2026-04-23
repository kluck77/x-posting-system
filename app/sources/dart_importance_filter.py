"""OpenDart 공시 전용 중요도 필터.

일반 뉴스 키워드 기준이 아닌 공시 유형 기반 점수 산출.
- 공시 유형 (상장폐지/실적발표/임원변동 등) → base 점수
- 핵심 기업 / 크립토 관련 기업 → 보너스
- 최종 0~100 clip
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# 공시 유형별 기본 점수 (내림차순 검사)
DART_TYPE_SCORES: dict[str, int] = {
    # 즉시 포스팅 (70점 이상)
    "상장폐지":     90,
    "거래정지":     90,
    "불성실공시":   85,
    "영업정지":     85,
    "파산":         95,
    "워크아웃":     90,
    "대규모계약":   75,
    "유상증자":     70,
    "무상증자":     65,
    "주식매수선택권": 60,

    # 중요 공시 (50~70점)
    "실적발표":     75,
    "매출액변동":   70,
    "영업이익변동": 70,
    "잠정실적":     75,
    "전환사채":     55,
    "신주인수권":   55,
    "임원변동":     60,
    "최대주주변동": 70,
    "자기주식":     55,
    "배당":         60,

    # 낮은 공시 (40점 이하)
    "내부거래":     35,
    "기재정정":     30,
    "자회사":       40,
    "담보":         30,
    "소송":         45,
}

# 핵심 기업 가중치 (이 기업이면 +20점)
KEY_COMPANIES: list[str] = [
    "삼성전자", "SK하이닉스", "카카오", "네이버",
    "현대차", "기아", "LG에너지솔루션", "포스코",
    "셀트리온", "크래프톤", "업비트", "빗썸",
    "두나무", "카카오페이", "토스", "신한",
    "KB금융", "하나금융", "우리금융", "DGB",
    "BNK", "코인원", "고팍스",
]

# 크립토 관련 기업 가중치 (+30점, KEY_COMPANIES 보다 우선)
CRYPTO_COMPANIES: list[str] = [
    "두나무", "빗썸", "코인원", "고팍스",
    "업비트", "카카오페이", "크래프톤",
]


def score_dart(title: str, company: str) -> dict:
    """공시 중요도 점수 산출.

    Args:
        title: 공시 제목
        company: 공시 대상 기업명 (IntelItem.entity 또는 source)

    Returns:
        {score:int, category:str, reason:str, matched_type:str|None}
    """
    base_score = 35  # 기본값 (unknown 유형)

    # 공시 유형 매칭 (내림차순 dict, 제목에 포함되는 첫 key 사용)
    matched_type: str | None = None
    for dart_type, type_score in DART_TYPE_SCORES.items():
        if dart_type in (title or ""):
            base_score = type_score
            matched_type = dart_type
            break

    # 기업 가중치 (CRYPTO 가 KEY 보다 우선)
    company_bonus = 0
    company_str = company or ""
    if any(c in company_str for c in CRYPTO_COMPANIES):
        company_bonus = 30
    elif any(c in company_str for c in KEY_COMPANIES):
        company_bonus = 20

    final_score = min(base_score + company_bonus, 100)

    if final_score >= 70:
        category = "dart_critical"
    elif final_score >= 55:
        category = "dart_important"
    else:
        category = "dart_routine"

    reason = (
        f"공시유형={matched_type or '기타'} "
        f"base={base_score} "
        f"기업가중치=+{company_bonus}"
    )

    logger.debug(
        f"[DartFilter] {company_str} | {(title or '')[:30]} | {final_score}점"
    )
    return {
        "score":        final_score,
        "category":     category,
        "reason":       reason,
        "matched_type": matched_type,
    }


def should_post(title: str, company: str, threshold: int = 55) -> bool:
    """threshold 이상이면 포스팅 가치 있음."""
    return score_dart(title, company)["score"] >= threshold
