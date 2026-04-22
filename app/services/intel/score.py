"""
Intel priority score / label / human-readable reason
=====================================================
모두 순수 함수. 네트워크/DB 없음. AI 호출 없음.
collect 시점에 1 회 실행되어 IntelItem row 에 저장된다.

Rubric (base 0, 합산 후 clamp [0,100]):
  + 크립토 핵심 키워드              : +25
  + 정책/규제 키워드                : +15
  + R2 allow-list entity            : +15
  + R4 numeric 변화                 : +10
  + source_type 가중치              : +0 ~ +25
  + entity 문자열 유의미성          : +5
  - generic macro noise 감점        : -25
  - title 너무 짧음 (< 25자)        : -5

Label:
  >= 80  → "strong"  (🔥 강추천)
  60~79  → "watch"   (👀 볼만함)
  40~59  → "weak"    (➖ 약함)
  < 40   → "noise"   (📉 기본 접기)
"""

from __future__ import annotations

from app.services.intel.filter import (
    R1_CRYPTO_KEYWORDS,
    R2_ENTITIES,
    R3_STAGES_EN,
    R3_STAGES_KO,
    R4_NUMERIC_PATTERN,
)
from app.services.intel.schema import NormalizedIntelItem


# 정책/규제 관련 가중 키워드 (R3 stage + 추가 규제 어휘 + 공시 signal)
_POLICY_KEYWORDS: tuple[str, ...] = R3_STAGES_EN + R3_STAGES_KO + (
    "regulation", "policy", "sanction", "enforcement", "ruling",
    "규제", "제재", "정책", "법안",
    # Korea 공시 핵심 signal — "사업목적 추가" 가 Korea Filings 의 전형
    "사업목적", "전자공시", "주요사항보고서",
)

# source_type 가중치
_SOURCE_TYPE_WEIGHT: dict[str, int] = {
    "filing":       25,
    "bill":         20,
    "enforcement":  25,
    "policy":       20,
    "fund":         15,
    "crypto_news":   5,
    "market_news":   0,
}

# human reason 매핑 — source_type 한국어 짧은 라벨
_SOURCE_TYPE_KR: dict[str, str] = {
    "filing":       "Korea 공시",
    "bill":         "US 법안",
    "enforcement":  "제재/집행",
    "policy":       "정책",
    "fund":         "자금 흐름",
    "crypto_news":  "크립토 뉴스",
    "market_news":  "마켓 뉴스",
}

# human reason 매핑 — R3 영어 스테이지를 한국어 구로
_STAGE_KR: dict[str, str] = {
    "filed":      "제출",
    "proposed":   "발의",
    "approved":   "승인",
    "hearing":    "청문 단계",
    "comment":    "의견수렴",
    "disposal":   "처분",
    "sanction":   "제재",
}

_TITLE_MIN_LEN = 25
_NOISE_PENALTY = -25
_SHORT_TITLE_PENALTY = -5


def _haystack(item: NormalizedIntelItem) -> str:
    return " ".join([
        item.title or "",
        item.summary or "",
        item.entity or "",
    ])


def _has_any(text: str, tokens: tuple[str, ...]) -> bool:
    low = text.lower()
    return any(t.lower() in low for t in tokens)


def _find_first(text: str, tokens: tuple[str, ...]) -> str | None:
    low = text.lower()
    for t in tokens:
        if t.lower() in low:
            return t
    return None


def compute_priority_score(item: NormalizedIntelItem) -> int:
    """0~100 정수 점수."""
    text = _haystack(item)
    score = 0

    crypto_hit = _has_any(text, R1_CRYPTO_KEYWORDS)
    policy_hit = _has_any(text, _POLICY_KEYWORDS)
    entity_hit = _has_any(text, R2_ENTITIES)
    numeric_hit = bool(R4_NUMERIC_PATTERN.search(text))

    if crypto_hit:
        score += 25
    if policy_hit:
        score += 15
    if entity_hit:
        score += 15
    if numeric_hit:
        score += 10

    score += _SOURCE_TYPE_WEIGHT.get(item.source_type, 0)

    if item.entity and len(item.entity.strip()) >= 2:
        score += 5

    # generic macro noise 감점
    if item.source_type == "market_news" and not crypto_hit and not policy_hit:
        score += _NOISE_PENALTY      # -25

    # crypto_news 중 정책/엔티티 신호 없는 일반 가격 뉴스 부분 감점
    if item.source_type == "crypto_news" and not policy_hit and not entity_hit:
        score += -15

    # 지나치게 짧은 제목 감점
    if len((item.title or "").strip()) < _TITLE_MIN_LEN:
        score += _SHORT_TITLE_PENALTY

    return max(0, min(100, score))


def derive_score_label(score: int) -> str:
    """score → 4 단계 라벨."""
    if score >= 80:
        return "strong"
    if score >= 60:
        return "watch"
    if score >= 40:
        return "weak"
    return "noise"


def compose_why_flagged_human(
    item: NormalizedIntelItem,
    flagged_reason: str,
    score: int,
) -> str:
    """
    raw flagged_reason + item 특성 → 한국어 1 줄 요약 (최대 120자).
    AI 호출 없음. 템플릿 조합.
    """
    parts: list[str] = []
    text_low = _haystack(item).lower()

    # 단계 변화 라벨
    stage = _find_first(
        _haystack(item), R3_STAGES_EN + R3_STAGES_KO,
    )
    if stage:
        stage_low = stage.lower()
        if stage_low in _STAGE_KR:
            parts.append(_STAGE_KR[stage_low])
        else:
            parts.append(stage)  # 한국어 원어 그대로

    # source_type 라벨
    st_kr = _SOURCE_TYPE_KR.get(item.source_type)
    if st_kr:
        parts.append(st_kr)

    # entity 괄호 표기
    if item.entity and len(item.entity.strip()) >= 2:
        parts.append(f"({item.entity.strip()[:40]})")

    # 크립토 핵심 키워드
    if any(k.lower() in text_low for k in R1_CRYPTO_KEYWORDS):
        parts.append("크립토 핵심 키워드")

    # 숫자 변화
    if R4_NUMERIC_PATTERN.search(_haystack(item)):
        parts.append("수치 변화")

    # noise 는 마지막에 덧붙여 우선순위 낮음을 명시
    if score < 40:
        if not parts:
            parts.append("일반 매크로 뉴스 — 우선순위 낮음")
        else:
            parts.append("우선순위 낮음")

    # dedup 인접 중복 제거
    seen = set()
    dedup_parts: list[str] = []
    for p in parts:
        if p in seen:
            continue
        seen.add(p)
        dedup_parts.append(p)

    text = " · ".join(dedup_parts).strip()
    if not text:
        # flagged_reason 이 있으면 fallback 으로 첫 항목만 취한다 (노출 최소).
        text = (flagged_reason.split(";")[0] if flagged_reason else "신호 없음")
    return text[:120]


# ─── Phase 6 — 시간 감쇠 / 슬롯 분류 / cleanup 후보 ───────────────────

def compute_freshness_penalty(age_hours: float) -> int:
    """
    경과 시간에 따른 감쇠 계단:
       0 <= age <  2h → 0
       2 <= age <  6h → 5
       6 <= age < 12h → 10
      12 <= age < 24h → 20
      age >= 24h      → 30
    """
    if age_hours is None or age_hours < 0:
        age_hours = 0.0
    if age_hours < 2:
        return 0
    if age_hours < 6:
        return 5
    if age_hours < 12:
        return 10
    if age_hours < 24:
        return 20
    return 30


def compute_display_score(priority_score: int, penalty: int) -> int:
    """표시/정렬용 점수 = max(0, priority - penalty). priority 원값은 유지."""
    try:
        p = int(priority_score or 0)
        pen = int(penalty or 0)
    except Exception:
        return 0
    return max(0, p - pen)


# Visibility window (Phase 6 지시 그대로)
_WINDOW_MAIN_STRONG_WATCH_H = 24.0
_WINDOW_AGED_STRONG_WATCH_H = 24.0 * 7
_WINDOW_MAIN_WEAK_H = 12.0
_WINDOW_AGED_WEAK_H = 72.0
_WINDOW_MAIN_NOISE_H = 6.0


def classify_visibility_slot(
    label: str,
    age_hours: float,
    promotion_status: str,
) -> str:
    """
    'main' | 'aged' | 'secondary' | 'hidden'

    - strong / watch : 24h main, 7d 까지 aged, 그 뒤 hidden
    - weak           : 12h main, 72h 까지 aged, 그 뒤 hidden
    - noise          : 6h secondary, 그 뒤 hidden
    - promotion_status == 'sent' 이면 hidden 강등 대신 aged 유지 (이력 보존)
    """
    lab = (label or "noise").lower()
    age = float(age_hours or 0.0)
    st = (promotion_status or "none").lower()

    if lab in ("strong", "watch"):
        if age <= _WINDOW_MAIN_STRONG_WATCH_H:
            slot = "main"
        elif age <= _WINDOW_AGED_STRONG_WATCH_H:
            slot = "aged"
        else:
            slot = "hidden"
    elif lab == "weak":
        if age <= _WINDOW_MAIN_WEAK_H:
            slot = "main"
        elif age <= _WINDOW_AGED_WEAK_H:
            slot = "aged"
        else:
            slot = "hidden"
    else:  # noise 또는 알 수 없는 라벨
        if age <= _WINDOW_MAIN_NOISE_H:
            slot = "secondary"
        else:
            slot = "hidden"

    # 전송된 이력은 최소 aged 로 보존
    if st == "sent" and slot == "hidden":
        slot = "aged"
    return slot


def is_cleanup_candidate(
    label: str,
    age_hours: float,
    promotion_status: str,
) -> bool:
    """
    자동 삭제 아님. UI 에서 정리 후보 타일/필터로 노출.

      sent                → 항상 False (보존)
      noise + 48h+        → True
      weak  + 72h+        → True
      strong/watch + 7d+  → True
      그 외               → False
    """
    lab = (label or "noise").lower()
    age = float(age_hours or 0.0)
    st = (promotion_status or "none").lower()
    if st == "sent":
        return False
    if lab == "noise" and age > 48:
        return True
    if lab == "weak" and age > 72:
        return True
    if lab in ("strong", "watch") and age > 24 * 7:
        return True
    return False
