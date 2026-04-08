"""
후보 선별 필터 (Phase A — heuristic only)
==========================================
초안 생성 전에 source_item 을 1차 선별한다.

Phase A 범위:
- L1: AI 0비용 키워드 블랙리스트 즉시 탈락
- 휴리스틱 점수: Global Linkage / Korea Specificity /
  Foreign Reader Interest / Explanation Value / Series Repeat Value
  (합계 85점, 5단계 버킷)
- 컷라인: PASS >= 60 / HOLD 45~59 / REJECT <= 44

Phase A 범위 밖:
- Grok 연결, X 반응성, 적응형 컷라인, 대시보드 변경,
  중복 클러스터링, 소스 신뢰도 학습, 언어 판정 확장,
  24h 자동 폐기 스케줄러
"""

import json
import logging
from dataclasses import dataclass, field
from typing import Optional

from app.models.content import CandidateStatus, SourceItem

logger = logging.getLogger(__name__)


# =============================================================================
# 컷라인 상수 (확정본)
# =============================================================================

CUTLINE_PASS: int = 60           # 60 이상 → passed
CUTLINE_HOLD_MIN: int = 45       # 45~59  → hold
CUTLINE_REJECT_MAX: int = 44     # 44 이하 → rejected_score

SCORE_MAX_TOTAL: int = 85        # 축별 합계 (25 + 20 + 20 + 10 + 10)


# =============================================================================
# 축별 버킷 (5단계 granularity: 0 / 25% / 50% / 75% / 100%)
# =============================================================================

BUCKET_25 = (0, 6, 13, 19, 25)   # 25점 축
BUCKET_20 = (0, 5, 10, 15, 20)   # 20점 축
BUCKET_10 = (0, 3, 5, 8, 10)     # 10점 축


def _bucket_value(level: int, scale: int) -> int:
    """
    5단계 버킷 값을 돌려준다.

    Args:
        level: 0~4 (0=없음, 4=최고)
        scale: 25 / 20 / 10

    Returns:
        해당 버킷의 점수값
    """
    if level < 0:
        level = 0
    if level > 4:
        level = 4
    if scale == 25:
        return BUCKET_25[level]
    if scale == 20:
        return BUCKET_20[level]
    if scale == 10:
        return BUCKET_10[level]
    raise ValueError(f"지원하지 않는 scale: {scale}")


# =============================================================================
# L1 키워드 블랙리스트 (초기 최소 범위 — 확정본)
# =============================================================================
#
# 이 목록은 Phase A에서 고정이다. 넓히지 않는다.
# 의미:
#   - 연예 / 아이돌 / 배우 / 축제 / 날씨 / 화재 / 살인 / 사고
#   - 지역 행사
#   - 국내 정쟁 디테일 키워드
#
# 해외 독자가 한국을 이해하는 데 도움이 안 되는 유형을 차단한다.

L1_BLACKLIST_KEYWORDS: tuple[str, ...] = (
    # 연예/아이돌/배우
    "연예", "연예인", "아이돌", "배우", "걸그룹", "보이그룹",
    # 축제/지역 행사
    "축제", "지역축제", "지역 행사", "지역행사",
    # 날씨
    "날씨", "기온", "한파", "폭염", "장마",
    # 화재/사고/살인
    "화재", "불났", "살인", "살해", "사망사고", "사고로",
    # 국내 정쟁 디테일 (해외 독자 가치 낮음)
    "여야 공방", "당대표", "원내대표", "최고위원", "공천", "탈당",
    "계파", "친명", "친윤", "비명", "비윤",
)


def _contains_any(text: str, keywords: tuple[str, ...]) -> Optional[str]:
    """키워드 중 하나라도 포함되면 해당 키워드를 돌려준다."""
    for kw in keywords:
        if kw and kw in text:
            return kw
    return None


# =============================================================================
# 결과 dataclass
# =============================================================================

@dataclass
class CandidateResult:
    """후보 선별 결과."""
    status: CandidateStatus
    score: int
    breakdown: dict = field(default_factory=dict)

    def breakdown_json(self) -> str:
        return json.dumps(self.breakdown, ensure_ascii=False)


# =============================================================================
# L1 필터
# =============================================================================

def run_l1_filter(title: str, source_text: str) -> Optional[str]:
    """
    L1 키워드 블랙리스트 필터.

    Returns:
        걸린 키워드 문자열 (탈락), 또는 None (통과)
    """
    combined = f"{title}\n{source_text}"
    hit = _contains_any(combined, L1_BLACKLIST_KEYWORDS)
    if hit:
        logger.info(f"L1 탈락: keyword='{hit}'")
    return hit


# =============================================================================
# 휴리스틱 점수 계산 (축별 0~4 단계)
# =============================================================================
#
# Phase A 는 keyword heuristic 만 사용한다.
# 없는 필드는 추정하지 않는다. (네이버 메타, 발행시각, 조회수 등 사용 금지)
# 사용 가능한 필드: title / source_text / source_type / language / url

# --- 축 1: Global Linkage (25점) ---
# 한국 이슈가 글로벌 맥락(미국/중국/일본/EU/글로벌시장/반도체/AI/원자재/환율 등)과
# 연결되는 정도. 해외 독자가 "이게 나랑 무슨 상관이지?" 에 답할 수 있는지.
GLOBAL_LINKAGE_KEYWORDS = (
    "미국", "중국", "일본", "eu", "유럽", "글로벌", "세계",
    "nato", "g7", "g20", "유엔", "un ",
    "수출", "수입", "무역", "관세", "tariff",
    "반도체", "semiconductor", "chip", "samsung", "sk하이닉스", "tsmc",
    "ai", "인공지능", "chatgpt", "openai", "nvidia",
    "환율", "달러", "엔화", "위안", "원자재", "유가", "oil",
    "global", "export", "import", "china", "japan", "us ", "united states",
)

# --- 축 2: Korea Specificity (20점) ---
# "한국이기 때문에" 의미가 있는 구조적 주제인지.
# (저출산, 인구, 북한, 재벌, 병역, 전세, 비자, 이민, 통일 등)
KOREA_SPECIFICITY_KEYWORDS = (
    "한국", "korea", "korean", "south korea",
    "저출산", "출산율", "인구", "고령화", "저출생",
    "북한", "north korea", "dprk", "nuclear", "김정은",
    "재벌", "chaebol", "samsung", "hyundai", "lg ", "sk ",
    "병역", "징병", "군복무",
    "전세", "jeonse", "부동산", "집값",
    "비자", "이민", "visa",
    "통일", "unification",
    "원화", "한국은행", "bok",
)

# --- 축 3: Foreign Reader Interest (20점) ---
# 한국 바깥 독자에게 실제로 궁금한 이야기인지.
# 글로벌 토픽과 겹치지만, 여기서는 "바깥에서 본 관심"을 본다.
FOREIGN_READER_INTEREST_KEYWORDS = (
    "kpop", "k-pop", "k pop", "bts", "blackpink", "newjeans",
    "kdrama", "k-drama", "netflix",
    "semiconductor", "chip", "ai ", "chatgpt",
    "north korea", "nuclear", "missile",
    "demographic", "birth rate", "aging",
    "economy", "recession", "inflation", "won",
    "seoul", "busan",
    "samsung", "hyundai", "lg ",
    "visa", "immigration",
)

# --- 축 4: Explanation Value (10점) ---
# "왜 이 일이 일어나는지"를 설명할 가치가 있는지.
# 구조/정책/제도/배경이 있어야 설명 가치가 높다.
EXPLANATION_VALUE_KEYWORDS = (
    "정책", "policy", "제도", "개혁", "reform", "규제", "regulation",
    "법안", "bill", "law", "배경", "구조", "structural",
    "원인", "because", "왜", "why",
    "분석", "analysis", "outlook", "전망",
)

# --- 축 5: Series / Repeat Value (10점) ---
# 한 번 설명해두면 이후에도 계속 참조 가능한 시리즈성 주제인지.
# 일회성 뉴스(사고/화재/스캔들)는 0점에 가깝게.
SERIES_REPEAT_VALUE_KEYWORDS = (
    "시리즈", "series", "장기", "구조적", "structural",
    "저출산", "고령화", "인구", "demographic",
    "재벌", "chaebol", "전세", "jeonse",
    "북한", "nuclear",
    "반도체", "semiconductor",
    "ai", "인공지능",
)


def _count_hits(text: str, keywords: tuple[str, ...]) -> int:
    """단순 포함 카운트 (set 처리로 같은 키워드 중복 제거)."""
    hits = {kw for kw in keywords if kw and kw in text}
    return len(hits)


def _hits_to_level(hits: int) -> int:
    """
    키워드 히트 수 → 5단계 level (0~4).

    Phase A 초기 운영은 둥근 컷라인을 선호하므로
    의도적으로 단순한 매핑을 쓴다.
    """
    if hits <= 0:
        return 0
    if hits == 1:
        return 1
    if hits == 2:
        return 2
    if hits == 3:
        return 3
    return 4


def _score_axis(text: str, keywords: tuple[str, ...], scale: int) -> tuple[int, int, int]:
    """
    한 축의 점수를 계산한다.

    Returns:
        (hits, level, score)
    """
    hits = _count_hits(text, keywords)
    level = _hits_to_level(hits)
    score = _bucket_value(level, scale)
    return hits, level, score


def run_heuristic_score(title: str, source_text: str) -> tuple[int, dict]:
    """
    5축 휴리스틱 점수를 계산한다.

    Returns:
        (total_score, breakdown_dict)
        breakdown_dict 구조:
        {
          "global_linkage":           {"hits": int, "level": int, "score": int, "max": 25},
          "korea_specificity":        {"hits": int, "level": int, "score": int, "max": 20},
          "foreign_reader_interest":  {"hits": int, "level": int, "score": int, "max": 20},
          "explanation_value":        {"hits": int, "level": int, "score": int, "max": 10},
          "series_repeat_value":      {"hits": int, "level": int, "score": int, "max": 10},
          "total": int,
          "max_total": 85,
        }
    """
    combined = f"{title}\n{source_text}".lower()

    axes = [
        ("global_linkage",          GLOBAL_LINKAGE_KEYWORDS,          25),
        ("korea_specificity",       KOREA_SPECIFICITY_KEYWORDS,       20),
        ("foreign_reader_interest", FOREIGN_READER_INTEREST_KEYWORDS, 20),
        ("explanation_value",       EXPLANATION_VALUE_KEYWORDS,       10),
        ("series_repeat_value",     SERIES_REPEAT_VALUE_KEYWORDS,     10),
    ]

    breakdown: dict = {}
    total = 0
    for name, keywords, scale in axes:
        hits, level, score = _score_axis(combined, keywords, scale)
        breakdown[name] = {
            "hits": hits,
            "level": level,
            "score": score,
            "max": scale,
        }
        total += score

    breakdown["total"] = total
    breakdown["max_total"] = SCORE_MAX_TOTAL
    return total, breakdown


# =============================================================================
# 컷라인 판정
# =============================================================================

def classify_by_cutline(total_score: int) -> CandidateStatus:
    """
    heuristic 점수 → CandidateStatus.

    Rules:
        >= CUTLINE_PASS(60)            → PASSED
        CUTLINE_HOLD_MIN(45) ~ 59      → HOLD
        <= CUTLINE_REJECT_MAX(44)      → REJECTED_SCORE
    """
    if total_score >= CUTLINE_PASS:
        return CandidateStatus.PASSED
    if total_score >= CUTLINE_HOLD_MIN:
        return CandidateStatus.HOLD
    return CandidateStatus.REJECTED_SCORE


# =============================================================================
# 퍼블릭 엔트리 포인트
# =============================================================================

def evaluate_candidate(title: str, source_text: str) -> CandidateResult:
    """
    title + source_text 에 대해 Phase A 선별을 수행한다.

    순서:
      1) L1 키워드 블랙리스트 → 걸리면 즉시 REJECTED_L1 (점수 0)
      2) 5축 휴리스틱 점수 계산
      3) 컷라인으로 PASSED / HOLD / REJECTED_SCORE 분류

    Returns:
        CandidateResult
    """
    # 1) L1
    l1_hit = run_l1_filter(title, source_text)
    if l1_hit:
        breakdown = {
            "l1_hit": l1_hit,
            "total": 0,
            "max_total": SCORE_MAX_TOTAL,
        }
        return CandidateResult(
            status=CandidateStatus.REJECTED_L1,
            score=0,
            breakdown=breakdown,
        )

    # 2) heuristic score
    total, breakdown = run_heuristic_score(title, source_text)

    # 3) cutline
    status = classify_by_cutline(total)

    return CandidateResult(status=status, score=total, breakdown=breakdown)


def evaluate_source_item(source_item: SourceItem) -> CandidateResult:
    """
    SourceItem 객체에 대한 편의 래퍼.
    DB 쓰기는 하지 않는다. 호출자가 반영해야 한다.
    """
    return evaluate_candidate(
        title=source_item.title or "",
        source_text=source_item.source_text or "",
    )


def apply_result_to_source(source_item: SourceItem, result: CandidateResult) -> None:
    """
    평가 결과를 SourceItem 컬럼에 반영한다. (commit은 호출자 책임)
    """
    source_item.candidate_status = result.status
    source_item.candidate_score = result.score
    source_item.candidate_score_breakdown = result.breakdown_json()
