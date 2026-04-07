# app/services/classifier.py
# 카테고리별 키워드 + 위험도 분류 로직
# prediction_service.py 에서 ContentCategory, RiskLevel 을 import해서 사용

import logging
from app.models.content import ContentCategory, RiskLevel

logger = logging.getLogger(__name__)

CATEGORY_KEYWORDS = {
    ContentCategory.POLITICS: [
        "election", "president", "party", "opposition", "vote", "parliament",
        "politician", "political", "대통령", "선거", "정당", "국회", "여당", "야당",
    ],
    ContentCategory.POLICY: [
        "policy", "regulation", "law", "bill", "reform", "ministry",
        "government", "subsidy", "tax", "legislation", "규제", "정책", "법안",
    ],
    ContentCategory.ECONOMY: [
        "economy", "gdp", "inflation", "market", "stock", "won",
        "trade", "export", "import", "interest rate", "unemployment",
        "경제", "주식", "환율", "금리", "수출", "무역",
    ],
    ContentCategory.SOCIETY: [
        "society", "social", "demographic", "population", "birth rate",
        "aging", "education", "housing", "inequality", "welfare",
        "사회", "인구", "출산", "고령화", "교육",
    ],
    ContentCategory.KPOP_CULTURE: [
        "kpop", "k-pop", "drama", "hallyu", "korean wave", "idol",
        "entertainment", "bts", "blackpink", "한류", "아이돌", "드라마",
    ],
}


def classify_category(title: str, text: str) -> ContentCategory:
    combined = f"{title} {text}".lower()
    scores = {}
    for category, keywords in CATEGORY_KEYWORDS.items():
        scores[category] = sum(1 for kw in keywords if kw.lower() in combined)
    if scores:
        best = max(scores, key=scores.get)
        if scores[best] > 0:
            return best
    return ContentCategory.EVERGREEN


def classify_risk(title: str, text: str, category: ContentCategory):
    combined = f"{title} {text}".lower()
    reasons = []
    sensitive_categories = {
        ContentCategory.POLITICS, ContentCategory.POLICY,
        ContentCategory.ECONOMY, ContentCategory.SOCIETY,
    }
    base_risk = RiskLevel.LOW
    if category in sensitive_categories:
        base_risk = RiskLevel.MEDIUM
        reasons.append(f"카테고리 '{category.value}'는 민감한 주제")
    high_risk_kw = [
        "scandal", "corruption", "arrest", "protest", "controversy",
        "crisis", "conflict", "death", "war", "nuclear", "north korea",
    ]
    found_high = [kw for kw in high_risk_kw if kw in combined]
    if found_high:
        base_risk = RiskLevel.HIGH
        reasons.append(f"고위험 키워드: {', '.join(found_high[:3])}")
    if not reasons:
        reasons.append("특별한 위험 요소 없음")
    return base_risk, "; ".join(reasons)
