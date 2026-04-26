"""사건 카테고리 자동 판별 + 회차 가중치 (7 아키타입 DNA)."""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


CATEGORY_KEYWORDS = {
    "crypto": [
        "비트코인", "btc", "이더리움", "eth", "스테이블코인",
        "usdt", "usdc", "테더", "코인", "거래소",
        "업비트", "빗썸", "코인베이스", "바이낸스",
        "디파이", "nft", "온체인", "지갑", "동결", "freeze",
        "polymarket", "blockchain", "defi", "dex",
    ],
    "macro": [
        "fomc", "fed", "연준", "기준금리", "한은", "금통위",
        "cpi", "ppi", "인플레이션", "고용", "실업률",
        "달러", "원화", "환율", "국채", "채권", "수익률",
        "경기침체", "recession", "베센트", "파월", "이창용",
    ],
    "semi": [
        "반도체", "엔비디아", "nvidia", "삼성전자", "sk하이닉스",
        "hbm", "tsmc", "마이크론", "인텔", "amd", "asml",
        "d램", "낸드", "파운드리", "팹",
    ],
    "policy": [
        "법안", "규제", "ofac", "sec", "금융위", "금감원",
        "이재명", "윤석열", "트럼프", "디지털자산기본법",
        "daba", "ai기본법", "etf",
    ],
    "geo": [
        "이란", "이스라엘", "중국", "대만", "러시아", "우크라이나",
        "전쟁", "제재", "관세", "무역", "동맹",
        "호르무즈", "남중국해", "북한",
    ],
    "real_estate": [
        "부동산", "아파트", "전세", "매매", "분양",
        "주담대", "ltv", "dsr", "pf",
    ],
    "equity": [
        "코스피", "코스닥", "주가", "종목", "etf",
        "외국인", "수급", "공매도",
    ],
}


# 카테고리별 7 아키타입 DNA 베이스라인 (합 100)
ARCHETYPE_BASELINE = {
    "crypto": {
        "trader": 40, "analyst": 25, "educator": 15,
        "contrarian": 10, "insider": 5,
        "satirist": 3, "narrator": 2,
    },
    "macro": {
        "analyst": 40, "educator": 25, "narrator": 15,
        "contrarian": 10, "trader": 5,
        "insider": 3, "satirist": 2,
    },
    "semi": {
        "analyst": 35, "trader": 25, "insider": 20,
        "educator": 10, "contrarian": 5,
        "narrator": 3, "satirist": 2,
    },
    "policy": {
        "insider": 35, "analyst": 30, "educator": 15,
        "narrator": 10, "contrarian": 5,
        "trader": 3, "satirist": 2,
    },
    "geo": {
        "analyst": 35, "narrator": 25, "insider": 20,
        "contrarian": 10, "educator": 5,
        "trader": 3, "satirist": 2,
    },
    "real_estate": {
        "analyst": 35, "educator": 25, "narrator": 20,
        "insider": 10, "trader": 5,
        "contrarian": 3, "satirist": 2,
    },
    "equity": {
        "trader": 35, "analyst": 30, "insider": 15,
        "educator": 10, "contrarian": 5,
        "narrator": 3, "satirist": 2,
    },
}


def detect_category(text: str) -> str:
    """텍스트에서 카테고리 자동 판별. 매치 없으면 macro."""
    if not text:
        return "macro"
    text_lower = text.lower()
    scores: dict[str, int] = {}
    for cat, keywords in CATEGORY_KEYWORDS.items():
        scores[cat] = sum(text_lower.count(kw.lower()) for kw in keywords)
    best = max(scores.items(), key=lambda x: x[1])
    return best[0] if best[1] > 0 else "macro"


def get_archetype_baseline(category: str) -> dict:
    return dict(ARCHETYPE_BASELINE.get(
        category, ARCHETYPE_BASELINE["macro"]
    ))


def format_archetype(weights: dict) -> str:
    if not weights:
        return ""
    return " / ".join(
        f"{k} {v}"
        for k, v in sorted(weights.items(), key=lambda x: -int(x[1] or 0))
    )
