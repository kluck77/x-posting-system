"""
비즈니스 분류 서비스 (Phase 5)
===============================
콘텐츠의 비즈니스 목적을 자동 분류합니다.

- business_tags: 콘텐츠의 비즈니스 역할 (growth, newsletter, premium_candidate 등)
- cta_type: 추천 CTA 유형
- monetization_score: 수익화 잠재력 점수 (0-100)
- asset_goal: 자산 목표 유형
- b2b_candidate: B2B 리서치 후보 여부
- b2b_target_audience / b2b_use_case: B2B 대상/용도

Layer 2 원칙: 이 서비스가 실패해도 Layer 1 파이프라인에 영향 없음.
"""

import json
import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# ─── 비즈니스 태그 키워드 매핑 ──────────────────────────────────────────

# 프리미엄 브리프 후보 키워드 (깊은 분석 가치가 있는 토픽)
PREMIUM_KEYWORDS = [
    "regulation", "규제", "reform", "개혁", "law", "법안", "amendment", "개정",
    "budget", "예산", "fiscal", "재정", "monetary", "통화", "interest rate", "금리",
    "demographic", "인구", "aging", "고령화", "birth rate", "출산율",
    "housing", "부동산", "real estate", "전세", "jeonse",
    "chaebol", "재벌", "conglomerate", "대기업",
    "semiconductor", "반도체", "battery", "배터리", "EV", "전기차",
    "trade", "무역", "export", "수출", "import", "수입", "tariff", "관세",
    "election", "선거", "presidential", "대통령", "party", "정당",
    "north korea", "북한", "defense", "국방", "military", "군사",
    "labor", "노동", "union", "노조", "minimum wage", "최저임금",
    "education", "교육", "university", "대학", "csat", "수능",
]

# B2B 리서치 후보 키워드 (외국 기업/투자자에게 유용)
B2B_KEYWORDS = [
    "regulation", "규제", "compliance", "foreign investment", "외국인 투자",
    "trade", "무역", "tariff", "관세", "supply chain", "공급망",
    "market entry", "진출", "licensing", "인허가",
    "semiconductor", "반도체", "battery", "배터리", "EV", "전기차",
    "labor", "노동", "visa", "비자", "hiring", "채용",
    "tax", "세금", "corporate tax", "법인세",
    "data privacy", "개인정보", "GDPR", "정보보호",
    "IPO", "상장", "M&A", "인수합병",
    "sanctions", "제재", "export control", "수출통제",
    "real estate", "부동산", "commercial", "상업",
    "infrastructure", "인프라", "logistics", "물류",
]

# 뉴스레터 푸시 키워드 (구독자가 궁금해할 토픽)
NEWSLETTER_KEYWORDS = [
    "explained", "설명", "guide", "가이드", "how", "why", "what",
    "history", "역사", "culture", "문화", "society", "사회",
    "comparison", "비교", "vs", "difference", "차이",
    "myth", "오해", "misconception", "truth", "진실",
    "daily life", "일상", "cost of living", "물가",
    "food", "음식", "travel", "여행", "language", "언어",
    "K-pop", "K-drama", "hallyu", "한류",
    "unique", "독특", "surprising", "놀라운",
]

# 리드 마그넷 후보 키워드 (무료 PDF/가이드 소재)
LEAD_MAGNET_KEYWORDS = [
    "guide", "가이드", "checklist", "체크리스트", "step by step", "단계별",
    "beginner", "초보", "101", "basics", "기초",
    "how to", "방법", "tips", "팁", "best", "최고",
    "complete", "완전", "ultimate", "ultimate guide",
    "free", "무료", "download", "다운로드",
    "template", "템플릿", "framework", "프레임워크",
]

# B2B 대상 독자 매핑
B2B_AUDIENCE_RULES = {
    "foreign_investors": ["investment", "투자", "stock", "주식", "market", "시장",
                          "IPO", "상장", "fund", "펀드", "bond", "채권"],
    "policy_makers": ["regulation", "규제", "law", "법", "policy", "정책",
                      "government", "정부", "ministry", "부처"],
    "supply_chain": ["semiconductor", "반도체", "battery", "배터리", "EV",
                     "manufacturing", "제조", "logistics", "물류", "trade", "무역"],
    "market_entry": ["market entry", "진출", "licensing", "인허가",
                     "franchise", "프랜차이즈", "startup", "스타트업"],
    "hr_talent": ["labor", "노동", "hiring", "채용", "visa", "비자",
                  "talent", "인재", "education", "교육"],
}

# B2B 활용 사례 매핑
B2B_USE_CASE_RULES = {
    "market_entry": ["market entry", "진출", "expansion", "확장"],
    "regulation_monitor": ["regulation", "규제", "law", "법", "compliance", "준수"],
    "risk_assessment": ["risk", "위험", "sanction", "제재", "north korea", "북한",
                        "geopolitical", "지정학"],
    "investment_research": ["investment", "투자", "IPO", "valuation", "기업가치"],
    "competitor_analysis": ["chaebol", "재벌", "Samsung", "삼성", "Hyundai", "현대",
                            "SK", "LG", "competitor", "경쟁"],
}

# 카테고리별 기본 CTA 매핑
CATEGORY_CTA_MAP = {
    "politics": "follow",
    "policy": "follow",
    "economy": "newsletter_signup",
    "society": "reply",
    "kpop_culture": "follow",
    "evergreen": "newsletter_signup",
    "crypto": "follow",
    "community": "reply",
}

# 카테고리별 기본 asset_goal
CATEGORY_ASSET_MAP = {
    "politics": "x_only",
    "policy": "premium_teaser",
    "economy": "newsletter_push",
    "society": "x_only",
    "kpop_culture": "x_only",
    "evergreen": "lead_magnet_push",
    "crypto": "newsletter_push",
    "community": "x_only",
}


@dataclass
class BusinessClassification:
    """비즈니스 분류 결과"""
    business_tags: list[str] = field(default_factory=list)
    cta_type: str = "follow"
    monetization_score: int = 0
    asset_goal: str = "x_only"
    premium_reason: str | None = None
    b2b_candidate: bool = False
    b2b_target_audience: str | None = None
    b2b_use_case: str | None = None


def classify_business(
    title: str,
    body: str,
    category: str,
    risk_level: str,
    topic_tags: list[str] | None = None,
) -> BusinessClassification:
    """
    콘텐츠의 비즈니스 목적을 자동 분류합니다.

    Args:
        title: 소스 제목
        body: 드래프트 본문
        category: ContentCategory 값
        risk_level: RiskLevel 값
        topic_tags: 기존 토픽 태그 (있으면)

    Returns:
        BusinessClassification 결과

    실패해도 기본값 반환 (Layer 2).
    """
    try:
        return _classify_business_inner(title, body, category, risk_level, topic_tags)
    except Exception as e:
        logger.warning(f"[BusinessClassifier] 분류 실패 (기본값 반환): {e}")
        return BusinessClassification(
            business_tags=["growth"],
            cta_type="follow",
            asset_goal="x_only",
        )


def _classify_business_inner(
    title: str,
    body: str,
    category: str,
    risk_level: str,
    topic_tags: list[str] | None,
) -> BusinessClassification:
    """실제 분류 로직."""
    combined = f"{title} {body}".lower()
    tags_text = " ".join(topic_tags).lower() if topic_tags else ""
    search_text = f"{combined} {tags_text}"

    result = BusinessClassification()

    # ── 1. 비즈니스 태그 분류 ──

    # 모든 콘텐츠는 기본적으로 growth
    result.business_tags.append("growth")

    # 프리미엄 후보 체크
    premium_hits = _count_keyword_hits(search_text, PREMIUM_KEYWORDS)
    if premium_hits >= 2:
        result.business_tags.append("premium_candidate")
        result.premium_reason = f"Premium topic signals: {premium_hits} keyword matches"

    # 뉴스레터 후보 체크
    newsletter_hits = _count_keyword_hits(search_text, NEWSLETTER_KEYWORDS)
    if newsletter_hits >= 2 or category in ("evergreen", "society", "economy"):
        result.business_tags.append("newsletter")

    # 리드 마그넷 후보 체크
    lead_magnet_hits = _count_keyword_hits(search_text, LEAD_MAGNET_KEYWORDS)
    if lead_magnet_hits >= 2 or category == "evergreen":
        result.business_tags.append("lead_magnet")

    # B2B 후보 체크
    b2b_hits = _count_keyword_hits(search_text, B2B_KEYWORDS)
    if b2b_hits >= 2:
        result.business_tags.append("b2b_candidate")
        result.b2b_candidate = True

    # 카테고리 기반 추가 태그
    if category in ("economy", "crypto"):
        if "data_story" not in result.business_tags:
            result.business_tags.append("data_story")
    if category == "evergreen":
        result.business_tags.append("explainer")
    if risk_level == "high" and category in ("politics", "policy"):
        result.business_tags.append("urgent_news")

    # 스폰서 후보 (특정 산업/기업 관련)
    sponsor_keywords = ["samsung", "삼성", "hyundai", "현대", "SK", "LG",
                        "startup", "스타트업", "brand", "브랜드"]
    if _count_keyword_hits(search_text, sponsor_keywords) >= 1:
        result.business_tags.append("sponsor_candidate")

    # 중복 제거
    result.business_tags = list(dict.fromkeys(result.business_tags))

    # ── 2. CTA 유형 결정 ──

    if "premium_candidate" in result.business_tags:
        result.cta_type = "premium_waitlist"
    elif "b2b_candidate" in result.business_tags:
        result.cta_type = "b2b_inquiry"
    elif "lead_magnet" in result.business_tags:
        result.cta_type = "lead_magnet"
    elif "newsletter" in result.business_tags:
        result.cta_type = "newsletter_signup"
    else:
        result.cta_type = CATEGORY_CTA_MAP.get(category, "follow")

    # ── 3. 수익화 점수 계산 ──

    score = 10  # 기본 (X reach 가치)

    if "premium_candidate" in result.business_tags:
        score += 30
    if "b2b_candidate" in result.business_tags:
        score += 25
    if "newsletter" in result.business_tags:
        score += 15
    if "lead_magnet" in result.business_tags:
        score += 10
    if "sponsor_candidate" in result.business_tags:
        score += 10
    if "data_story" in result.business_tags:
        score += 5
    if "explainer" in result.business_tags:
        score += 5

    # 카테고리 보정
    if category in ("economy", "policy"):
        score += 10
    elif category == "crypto":
        score += 5

    # 리스크 감점 (고위험 = 수익화 어려움)
    if risk_level == "high":
        score -= 10
    elif risk_level == "low":
        score += 5

    result.monetization_score = max(0, min(100, score))

    # ── 4. 자산 목표 결정 ──

    if "premium_candidate" in result.business_tags:
        result.asset_goal = "premium_teaser"
    elif "b2b_candidate" in result.business_tags:
        result.asset_goal = "b2b_asset"
    elif "lead_magnet" in result.business_tags:
        result.asset_goal = "lead_magnet_push"
    elif "newsletter" in result.business_tags:
        result.asset_goal = "newsletter_push"
    else:
        result.asset_goal = CATEGORY_ASSET_MAP.get(category, "x_only")

    # ── 5. B2B 세부 분류 ──

    if result.b2b_candidate:
        result.b2b_target_audience = _detect_b2b_audience(search_text)
        result.b2b_use_case = _detect_b2b_use_case(search_text)

    return result


def _count_keyword_hits(text: str, keywords: list[str]) -> int:
    """텍스트에서 키워드 매칭 수를 카운트."""
    return sum(1 for kw in keywords if kw.lower() in text)


def _detect_b2b_audience(text: str) -> str | None:
    """B2B 대상 독자층 감지."""
    best = None
    best_score = 0
    for audience, keywords in B2B_AUDIENCE_RULES.items():
        score = _count_keyword_hits(text, keywords)
        if score > best_score:
            best = audience
            best_score = score
    return best


def _detect_b2b_use_case(text: str) -> str | None:
    """B2B 활용 사례 감지."""
    best = None
    best_score = 0
    for use_case, keywords in B2B_USE_CASE_RULES.items():
        score = _count_keyword_hits(text, keywords)
        if score > best_score:
            best = use_case
            best_score = score
    return best


def business_tags_to_json(tags: list[str]) -> str:
    """비즈니스 태그 리스트를 JSON 문자열로 변환."""
    return json.dumps(tags, ensure_ascii=False)


def business_tags_from_json(json_str: str | None) -> list[str]:
    """JSON 문자열에서 비즈니스 태그 리스트 추출."""
    if not json_str:
        return []
    try:
        return json.loads(json_str)
    except (json.JSONDecodeError, TypeError):
        return []
