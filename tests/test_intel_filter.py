"""
Intel filter / dedup 테스트 (Phase 1)
=====================================
schema / content_hash / decide_shortlist / reclassify_category.
외부 네트워크 없음.
"""

from datetime import datetime, timezone

import pytest

from app.services.intel.dedup import compute_content_hash
from app.services.intel.filter import decide_shortlist, reclassify_category
from app.services.intel.schema import IntelCategory, NormalizedIntelItem


def _make(**kw) -> NormalizedIntelItem:
    base = dict(
        source="unit",
        source_type="market_news",
        title="t", summary="", url=None,
        published_at=None, entity=None,
        category=IntelCategory.MARKET_COMPANY,
    )
    base.update(kw)
    return NormalizedIntelItem(**base)


# ── content_hash ─────────────────────────────────────────────────────────────

def test_content_hash_deterministic():
    h1 = compute_content_hash("open_dart", "http://x", "title-A", None)
    h2 = compute_content_hash("open_dart", "http://x", "title-A", None)
    assert h1 == h2
    assert len(h1) == 64


def test_content_hash_differs_on_published_at():
    t1 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    t2 = datetime(2026, 1, 2, tzinfo=timezone.utc)
    h1 = compute_content_hash("x", "u", "T", t1)
    h2 = compute_content_hash("x", "u", "T", t2)
    assert h1 != h2


def test_content_hash_differs_on_title():
    h1 = compute_content_hash("x", "u", "Title-A", None)
    h2 = compute_content_hash("x", "u", "Title-B", None)
    assert h1 != h2


# ── R1 keyword ───────────────────────────────────────────────────────────────

def test_r1_keyword_en():
    it = _make(title="SEC approves Bitcoin ETF", summary="")
    ok, reason = decide_shortlist(it)
    assert ok is True
    assert "R1:keyword=" in reason


def test_r1_keyword_ko():
    it = _make(title="가상자산 규제 법안 발의", summary="", source_type="crypto_news")
    ok, reason = decide_shortlist(it)
    assert ok is True
    assert "R1:keyword=" in reason


# ── R3 stage ─────────────────────────────────────────────────────────────────

def test_r3_stage_en():
    it = _make(title="Proposal approved by committee", source_type="crypto_news")
    ok, reason = decide_shortlist(it)
    assert ok is True
    assert "R3:stage=" in reason


def test_r3_stage_ko():
    it = _make(title="국회 청문회 일정", source_type="crypto_news")
    ok, reason = decide_shortlist(it)
    assert ok is True
    assert "R3:stage=" in reason


# ── R4 numeric ───────────────────────────────────────────────────────────────

def test_r4_numeric_money():
    it = _make(title="Company holds $1.2 billion in reserves", source_type="crypto_news")
    ok, reason = decide_shortlist(it)
    assert ok is True
    assert "R4:numeric=" in reason


def test_r4_numeric_percent():
    it = _make(title="지분 15% 확보", source_type="crypto_news")
    ok, reason = decide_shortlist(it)
    assert ok is True
    assert "R4:numeric=" in reason


# ── R5 auto source_type ──────────────────────────────────────────────────────

def test_r5_filing_auto_shortlist():
    it = _make(title="정기공시 제출", source_type="filing",
               category=IntelCategory.KOREA_FILINGS)
    ok, reason = decide_shortlist(it)
    assert ok is True
    assert "R5:source_type=filing" in reason


def test_r5_bill_auto_shortlist():
    it = _make(title="Generic bill title", source_type="bill",
               category=IntelCategory.US_POLICY_BILLS)
    ok, reason = decide_shortlist(it)
    assert ok is True
    assert "R5:source_type=bill" in reason


# ── no match ─────────────────────────────────────────────────────────────────

def test_no_match_returns_false():
    it = _make(title="Weather forecast sunny", summary="nothing relevant",
               source_type="crypto_news")
    ok, reason = decide_shortlist(it)
    assert ok is False
    assert reason == ""


# ── reclassify_category ──────────────────────────────────────────────────────

def test_reclassify_bill_without_crypto_becomes_macro():
    it = _make(title="Infrastructure funding act", source_type="bill",
               category=IntelCategory.US_POLICY_BILLS)
    out = reclassify_category(it)
    assert out == IntelCategory.MACRO_POLICY


def test_reclassify_market_news_with_crypto_becomes_asset_context():
    it = _make(title="Bitcoin price hits new high", source_type="market_news",
               category=IntelCategory.MARKET_COMPANY)
    out = reclassify_category(it)
    assert out == IntelCategory.ASSET_CONTEXT


def test_reclassify_keeps_default_when_no_rule():
    it = _make(title="Acme Corp Q3 results", source_type="market_news",
               category=IntelCategory.MARKET_COMPANY)
    out = reclassify_category(it)
    assert out == IntelCategory.MARKET_COMPANY


# ── flagged_reason format ────────────────────────────────────────────────────

def test_flagged_reason_format_uses_semicolons():
    it = _make(title="Bitcoin ETF approved hearing", source_type="crypto_news")
    ok, reason = decide_shortlist(it)
    assert ok is True
    # multiple reasons joined with "; "
    assert "; " in reason
