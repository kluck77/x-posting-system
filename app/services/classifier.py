"""
콘텐츠 분류 서비스
==================
콘텐츠의 카테고리와 위험 수준을 분류합니다.

위험 수준 규칙:
- politics, policy, economy, society -> 최소 medium 이상
- kpop_culture 중 논란성 -> medium 이상
- evergreen 교육 콘텐츠 -> low 가능
- v1에서는 모든 콘텐츠가 사람의 승인 필요
"""

import logging
import re
from app.models.content import ContentCategory, RiskLevel

logger = logging.getLogger(__name__)

# 카테고리 판별을 위한 키워드 사전
CATEGORY_KEYWORDS: dict[ContentCategory, list[str]] = {
    ContentCategory.POLITICS: [
        "election", "president", "party", "opposition", "democrat",
        "conservative", "progressive", "vote", "parliament", "assembly",
        "politician", "political", "대통령", "선거", "정당", "국회",
        "여당", "야당", "정치", "의원",
    ],
    ContentCategory.POLICY: [
        "policy", "regulation", "law", "bill", "reform", "ministry",
        "government", "subsidy", "tax", "legislation", "규제", "정책",
        "법안", "개혁", "세금", "법률", "제도",
    ],
    ContentCategory.ECONOMY: [
        "economy", "gdp", "inflation", "market", "stock", "won",
        "trade", "export", "import", "interest rate", "unemployment",
        "경제", "주식", "환율", "금리", "수출", "무역", "물가",
    ],
    ContentCategory.SOCIETY: [
        "society", "social", "demographic", "population", "birth rate",
        "aging", "education", "housing", "inequality", "welfare",
        "사회", "인구", "출산", "고령화", "교육", "주거", "복지",
    ],
    ContentCategory.KPOP_CULTURE: [
        "kpop", "k-pop", "drama", "hallyu", "korean wave", "idol",
        "entertainment", "kdrama", "k-drama", "bts", "blackpink",
        "한류", "아이돌", "드라마", "엔터", "연예",
    ],
}

# 고위험 키워드 (이것들이 포함되면 위험도 상승)
HIGH_RISK_KEYWORDS = [
    "scandal", "corruption", "arrest", "protest", "controversy",
    "crisis", "conflict", "death", "suicide", "abuse", "harassment",
    "war", "military", "nuclear", "north korea",
    "스캔들", "비리", "체포", "시위", "논란", "위기", "갈등",
    "사망", "학대", "전쟁", "군사", "핵", "북한",
]

# 중위험 키워드
MEDIUM_RISK_KEYWORDS = [
    "debate", "criticism", "oppose", "tension", "concern",
    "decline", "problem", "issue", "challenge", "risk",
    "논쟁", "비판", "반대", "긴장", "우려", "하락", "문제",
]


def classify_category(title: str, text: str) -> ContentCategory:
    """
    텍스트의 카테고리를 분류합니다.

    Args:
        title: 콘텐츠 제목
        text: 콘텐츠 본문

    Returns:
        분류된 ContentCategory
    """
    combined = f"{title} {text}".lower()
    scores: dict[ContentCategory, int] = {}

    for category, keywords in CATEGORY_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw.lower() in combined)
        scores[category] = score

    # 가장 높은 점수의 카테고리 선택
    if scores:
        best_category = max(scores, key=scores.get)
        if scores[best_category] > 0:
            logger.info(f"카테고리 분류: {best_category.value} (점수: {scores[best_category]})")
            return best_category

    # 매칭되는 키워드가 없으면 evergreen으로 분류
    logger.info("카테고리 분류: evergreen (기본값)")
    return ContentCategory.EVERGREEN


def classify_risk(title: str, text: str, category: ContentCategory) -> tuple[RiskLevel, str]:
    """
    콘텐츠의 위험 수준을 분류합니다.

    Args:
        title: 콘텐츠 제목
        text: 콘텐츠 본문
        category: 분류된 카테고리

    Returns:
        (위험 수준, 판단 근거) 튜플
    """
    combined = f"{title} {text}".lower()
    reasons = []

    # 1단계: 카테고리 기반 기본 위험도 설정
    # 정치, 정책, 경제, 사회 관련은 최소 medium
    sensitive_categories = {
        ContentCategory.POLITICS,
        ContentCategory.POLICY,
        ContentCategory.ECONOMY,
        ContentCategory.SOCIETY,
    }

    base_risk = RiskLevel.LOW
    if category in sensitive_categories:
        base_risk = RiskLevel.MEDIUM
        reasons.append(f"카테고리 '{category.value}'는 민감한 주제입니다")

    # 2단계: 고위험 키워드 체크
    found_high = [kw for kw in HIGH_RISK_KEYWORDS if kw.lower() in combined]
    if found_high:
        base_risk = RiskLevel.HIGH
        reasons.append(f"고위험 키워드 감지: {', '.join(found_high[:3])}")

    # 3단계: 중위험 키워드 체크 (이미 high가 아닌 경우만)
    if base_risk != RiskLevel.HIGH:
        found_medium = [kw for kw in MEDIUM_RISK_KEYWORDS if kw.lower() in combined]
        if found_medium and base_risk == RiskLevel.LOW:
            base_risk = RiskLevel.MEDIUM
            reasons.append(f"주의 키워드 감지: {', '.join(found_medium[:3])}")

    # 4단계: kpop_culture 특별 처리 (논란이 있으면 medium 이상)
    if category == ContentCategory.KPOP_CULTURE:
        controversy_words = ["scandal", "controversy", "dating", "military", "논란", "열애", "군대"]
        found_controversy = [w for w in controversy_words if w in combined]
        if found_controversy:
            if base_risk == RiskLevel.LOW:
                base_risk = RiskLevel.MEDIUM
            reasons.append(f"K-POP 논란 키워드: {', '.join(found_controversy[:3])}")

    if not reasons:
        reasons.append("특별한 위험 요소가 감지되지 않았습니다")

    reasoning = "; ".join(reasons)
    logger.info(f"위험도 분류: {base_risk.value} - {reasoning}")
    return base_risk, reasoning


def requires_approval(risk_level: RiskLevel, category: ContentCategory, auto_post_enabled: bool = False) -> bool:
    """
    이 콘텐츠가 사람의 승인이 필요한지 판단합니다.

    v1 규칙:
    - 기본적으로 모든 콘텐츠는 승인 필요
    - auto_post_enabled=True인 경우에만 low + evergreen 조합이 자동 게시 가능
    - politics/policy/economy/society/kpop 논란은 항상 승인 필요

    Args:
        risk_level: 위험 수준
        category: 콘텐츠 카테고리
        auto_post_enabled: 자동 게시 기능 활성화 여부

    Returns:
        True = 승인 필요, False = 자동 게시 가능
    """
    # 항상 승인이 필요한 카테고리
    always_require = {
        ContentCategory.POLITICS,
        ContentCategory.POLICY,
        ContentCategory.ECONOMY,
        ContentCategory.SOCIETY,
    }

    # 이 카테고리들은 무조건 승인 필요
    if category in always_require:
        return True

    # medium, high 위험도는 무조건 승인 필요
    if risk_level in (RiskLevel.MEDIUM, RiskLevel.HIGH):
        return True

    # 자동 게시가 꺼져있으면 무조건 승인 필요
    if not auto_post_enabled:
        return True

    # 여기까지 왔으면: auto_post_enabled=True + low risk + evergreen/kpop_culture
    # -> 자동 게시 가능 (하지만 v1에서는 기본값이 False이므로 거의 도달하지 않음)
    logger.info(f"자동 게시 허용: risk={risk_level.value}, category={category.value}")
    return False
