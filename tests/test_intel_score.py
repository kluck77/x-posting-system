"""
Intel score / label / human reason 테스트 (Phase 2)
====================================================
순수 함수 테스트 — 네트워크/DB 없음.
"""

from app.services.intel.schema import IntelCategory, NormalizedIntelItem
from app.services.intel.score import (
    compose_why_flagged_human,
    compute_priority_score,
    derive_score_label,
)


def _make(**kw) -> NormalizedIntelItem:
    base = dict(
        source="unit", source_type="market_news",
        title="generic title here filler", summary="", url=None,
        published_at=None, entity=None,
        category=IntelCategory.MARKET_COMPANY,
    )
    base.update(kw)
    return NormalizedIntelItem(**base)


# ── compute_priority_score ───────────────────────────────────────────────────

def test_bitcoin_etf_filing_scores_strong():
    it = _make(
        source="open_dart", source_type="filing",
        title="BlackRock filed spot Bitcoin ETF approved amendment",
        summary="SEC approved the spot BTC ETF after hearing.",
        entity="SEC", category=IntelCategory.CRYPTO_STREAM,
    )
    s = compute_priority_score(it)
    assert s >= 80
    assert derive_score_label(s) == "strong"


def test_korea_filing_scores_at_least_watch():
    it = _make(
        source="open_dart", source_type="filing",
        title="주요사항보고서 사업목적 추가 (한화)",
        summary="한화가 사업목적에 가상자산 추가를 공시했다.",
        entity="한화", category=IntelCategory.KOREA_FILINGS,
    )
    s = compute_priority_score(it)
    assert s >= 60


def test_us_bill_digital_asset_scores_watch_plus():
    it = _make(
        source="finnhub", source_type="bill",
        title="Digital Asset Market Structure Act proposed",
        summary="HR 4200 proposed in committee.",
        entity="HR 4200", category=IntelCategory.US_POLICY_BILLS,
    )
    s = compute_priority_score(it)
    assert s >= 60


def test_generic_macro_noise_scores_low():
    it = _make(
        source="finnhub", source_type="market_news",
        title="Stocks rebound as Iran peace talks in focus",
        summary="West Texas Intermediate settled.",
        entity=None, category=IntelCategory.MARKET_COMPANY,
    )
    s = compute_priority_score(it)
    assert s < 40
    assert derive_score_label(s) == "noise"


def test_market_news_with_crypto_keyword_is_watch():
    it = _make(
        source="finnhub", source_type="market_news",
        title="Company announces Bitcoin treasury allocation",
        summary="Holds $100 million in bitcoin.",
        entity="Acme", category=IntelCategory.ASSET_CONTEXT,
    )
    s = compute_priority_score(it)
    assert s >= 40  # weak or better
    assert derive_score_label(s) in {"weak", "watch", "strong"}


def test_short_title_penalty_applied():
    it_long = _make(
        source_type="crypto_news",
        title="Bitcoin ETF approved by SEC committee today",
    )
    it_short = _make(
        source_type="crypto_news",
        title="BTC ETF",  # very short
    )
    assert compute_priority_score(it_long) > compute_priority_score(it_short)


def test_score_clamped_to_100():
    it = _make(
        source="open_dart", source_type="filing",
        title="SEC approved Bitcoin ETF hearing $1 billion stablecoin custody",
        summary="ETF approved with 15% threshold.",
        entity="SEC", category=IntelCategory.CRYPTO_STREAM,
    )
    s = compute_priority_score(it)
    assert 0 <= s <= 100


# ── derive_score_label boundaries ─────────────────────────────────────────────

def test_label_boundaries():
    assert derive_score_label(0) == "noise"
    assert derive_score_label(39) == "noise"
    assert derive_score_label(40) == "weak"
    assert derive_score_label(59) == "weak"
    assert derive_score_label(60) == "watch"
    assert derive_score_label(79) == "watch"
    assert derive_score_label(80) == "strong"
    assert derive_score_label(100) == "strong"


# ── compose_why_flagged_human ─────────────────────────────────────────────────

def test_human_reason_mentions_stage_entity_and_crypto():
    it = _make(
        source="open_dart", source_type="filing",
        title="BlackRock filed Bitcoin ETF amendment approved",
        summary="SEC hearing.",
        entity="SEC", category=IntelCategory.CRYPTO_STREAM,
    )
    s = compute_priority_score(it)
    txt = compose_why_flagged_human(it, "R1:keyword=bitcoin; R3:stage=approved", s)
    assert "크립토" in txt
    assert "SEC" in txt
    assert "Korea 공시" in txt or "공시" in txt


def test_human_reason_noise_mentions_low_priority():
    it = _make(
        source="finnhub", source_type="market_news",
        title="Oil prices fluctuate as Middle East tensions continue",
        summary="Barrel prices moved slightly.",
    )
    s = compute_priority_score(it)
    txt = compose_why_flagged_human(it, "", s)
    assert "우선순위 낮음" in txt or "매크로" in txt


def test_human_reason_capped_at_120_chars():
    long_title = "bitcoin " * 40
    it = _make(
        source="finnhub", source_type="crypto_news",
        title=long_title, summary=long_title, entity="LongEntityName" * 5,
        category=IntelCategory.CRYPTO_STREAM,
    )
    s = compute_priority_score(it)
    txt = compose_why_flagged_human(it, "R1:keyword=bitcoin; R3:stage=approved; R4:numeric=5%", s)
    assert len(txt) <= 120


def test_human_reason_never_empty_with_fallback():
    it = _make(
        source="finnhub", source_type="market_news",
        title="blah blah blah blah blah blah",
        summary="nothing",
    )
    s = compute_priority_score(it)
    txt = compose_why_flagged_human(it, "", s)
    assert txt  # non-empty
