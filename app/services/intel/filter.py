"""
Intel shortlist filter — 룰 기반 (AI 없음)
===========================================
입력 NormalizedIntelItem 한 건에 대해:
  - shortlisted 여부
  - flagged_reason (R1~R5 매칭 요약)
  - 필요 시 category 재분류

규칙 (OR 결합 — 하나라도 매칭되면 shortlist):
  R1 키워드  : EN/KO 혼합 토큰 매칭
  R2 엔티티  : title/summary/entity 에 allow-list 기관/회사/법안 등장
  R3 단계변화: filed / approved / hearing / 청문회 / 의결 / ...
  R4 숫자변화: "$X billion", "조/억", "지분 N%", "보유 N"
  R5 source_type ∈ {filing, bill, policy, enforcement, fund}  → 자동 shortlist

카테고리 재분류:
  - source_type=bill 이고 crypto 키워드 0 → MACRO_POLICY
  - source_type=market_news 이고 crypto 키워드만 → ASSET_CONTEXT
"""

from __future__ import annotations

import re
from typing import Tuple

from app.services.intel.schema import IntelCategory, NormalizedIntelItem


# R1 — 키워드 (대소문자 무시)
R1_KEYWORDS_EN: tuple[str, ...] = (
    "bitcoin", "crypto", "etf", "treasury", "custody", "digital asset",
    "stablecoin",
)
R1_KEYWORDS_KO: tuple[str, ...] = (
    "가상자산", "비트코인", "ETF", "전자공시", "사업목적", "청문회", "규제",
)
R1_CRYPTO_KEYWORDS: tuple[str, ...] = (
    "bitcoin", "crypto", "digital asset", "stablecoin", "etf",
    "가상자산", "비트코인",
)

# R2 — 엔티티 allow-list (기관/회사/법안 등장 시 매칭)
R2_ENTITIES: tuple[str, ...] = (
    "microstrategy", "coinbase", "sec", "cftc", "tesla", "samsung",
    "blackrock", "fidelity",
    "한국전자공시", "금융위원회", "금감원", "국회", "기획재정부",
)

# R3 — 단계 변화
R3_STAGES_EN: tuple[str, ...] = (
    "filed", "proposed", "approved", "hearing", "comment", "disposal",
    "sanction",
)
R3_STAGES_KO: tuple[str, ...] = (
    "청문회", "의결", "제재", "승인", "처분", "발의",
)

# R4 — 숫자 변화 (금액 / 지분 / 보유)
R4_NUMERIC_PATTERN = re.compile(
    r"(\$[\d,.]+\s*(million|billion|trillion|조|억|천만)|"
    r"\d+(?:\.\d+)?\s*%|"
    r"보유\s?\d+|"
    r"지분\s?\d+)",
    re.IGNORECASE,
)

# R5 — source_type 자동 shortlist
R5_AUTO_TYPES: frozenset[str] = frozenset({
    "filing", "bill", "policy", "enforcement", "fund",
})


def _find_first(text: str, tokens: tuple[str, ...]) -> str | None:
    low = text.lower()
    for tok in tokens:
        if tok.lower() in low:
            return tok
    return None


def decide_shortlist(item: NormalizedIntelItem) -> Tuple[bool, str]:
    """
    (shortlisted, flagged_reason) 반환.
    flagged_reason 은 "R1:keyword=X; R3:stage=Y" 형태. 매칭 없으면 빈 문자열.
    """
    reasons: list[str] = []
    haystack = " ".join([
        item.title or "",
        item.summary or "",
        item.entity or "",
    ])

    # R1
    hit = _find_first(haystack, R1_KEYWORDS_EN + R1_KEYWORDS_KO)
    if hit:
        reasons.append(f"R1:keyword={hit}")

    # R2
    hit2 = _find_first(haystack, R2_ENTITIES)
    if hit2:
        reasons.append(f"R2:entity={hit2}")

    # R3
    hit3 = _find_first(haystack, R3_STAGES_EN + R3_STAGES_KO)
    if hit3:
        reasons.append(f"R3:stage={hit3}")

    # R4
    m = R4_NUMERIC_PATTERN.search(haystack)
    if m:
        reasons.append(f"R4:numeric={m.group(0)[:40]}")

    # R5
    if item.source_type in R5_AUTO_TYPES:
        reasons.append(f"R5:source_type={item.source_type}")

    shortlisted = bool(reasons)
    return shortlisted, "; ".join(reasons)


def reclassify_category(item: NormalizedIntelItem) -> IntelCategory:
    """
    adapter 가 배정한 기본 category 를 룰 기반으로 재분류.
    재분류 조건 불일치 시 원래 category 유지.
    """
    haystack = (item.title + " " + item.summary).lower()
    has_crypto = any(k.lower() in haystack for k in R1_CRYPTO_KEYWORDS)

    # bill + crypto 키워드 없음 → 일반 macro
    if item.source_type == "bill" and not has_crypto:
        return IntelCategory.MACRO_POLICY

    # market_news + crypto 키워드만 → asset context
    if item.source_type == "market_news" and has_crypto:
        return IntelCategory.ASSET_CONTEXT

    return item.category
