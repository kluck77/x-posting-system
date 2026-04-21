"""
Intel adapter 정규화 테스트 (Phase 1)
=====================================
- 키 없을 때 enabled=False, fetch() == []
- MockTransport 주입으로 sample JSON → NormalizedIntelItem 매핑 검증
- 네트워크 5xx/timeout 류 fail-soft (예외 없이 [])
"""

from __future__ import annotations

import json

import httpx
import pytest

from app.services.intel.adapters import base as _base_mod
from app.services.intel.adapters.coingecko import CoinGeckoAdapter
from app.services.intel.adapters.congress import CongressAdapter
from app.services.intel.adapters.cryptopanic import CryptoPanicAdapter
from app.services.intel.adapters.finnhub import FinnhubAdapter
from app.services.intel.adapters.newsapi import NewsApiAdapter
from app.services.intel.adapters.open_dart import OpenDartAdapter
from app.services.intel.schema import IntelCategory


def _patch_http(monkeypatch, payload, *, raise_exc: Exception | None = None):
    """_http_get 을 payload 반환 함수로 monkeypatch (네트워크 우회)."""
    async def fake_get(self, url, params=None, headers=None, timeout=10.0):
        if raise_exc:
            raise raise_exc
        return payload
    monkeypatch.setattr(_base_mod.BaseAdapter, "_http_get", fake_get, raising=True)


def _enable(monkeypatch, adapter_name: str):
    """settings.<adapter>_api_key 에 아무 값이나 채워 has_* property 를 True 로."""
    from app.config import settings
    monkeypatch.setattr(settings, f"{adapter_name}_api_key", "test-key", raising=False)


# ─── enabled=False 기본 ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_open_dart_disabled_returns_empty(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "open_dart_api_key", "", raising=False)
    a = OpenDartAdapter()
    assert a.enabled is False
    assert await a.fetch() == []


@pytest.mark.asyncio
async def test_congress_disabled_returns_empty(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "congress_api_key", "", raising=False)
    a = CongressAdapter()
    assert a.enabled is False
    assert await a.fetch() == []


# ─── stub adapters 항상 disabled ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_newsapi_stub_always_disabled():
    a = NewsApiAdapter()
    assert a.enabled is False
    assert await a.fetch() == []


@pytest.mark.asyncio
async def test_coingecko_stub_always_disabled():
    a = CoinGeckoAdapter()
    assert a.enabled is False
    assert await a.fetch() == []


# ─── open_dart sample → NormalizedIntelItem ──────────────────────────────────

@pytest.mark.asyncio
async def test_open_dart_maps_sample(monkeypatch):
    _enable(monkeypatch, "open_dart")
    sample = {
        "list": [
            {
                "corp_name": "한화",
                "report_nm": "주요사항보고서(사업목적 추가)",
                "rcept_dt": "20260401",
                "rcept_no": "20260401000001",
            }
        ]
    }
    _patch_http(monkeypatch, sample)
    items = await OpenDartAdapter().fetch(limit=5)
    assert len(items) == 1
    it = items[0]
    assert it.source == "open_dart"
    assert it.source_type == "filing"
    assert it.title.startswith("주요사항보고서")
    assert it.entity == "한화"
    assert it.category == IntelCategory.KOREA_FILINGS
    assert it.url and "20260401000001" in it.url
    assert it.raw_payload["rcept_no"] == "20260401000001"
    assert it.published_at and it.published_at.year == 2026


# ─── congress sample ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_congress_maps_sample(monkeypatch):
    _enable(monkeypatch, "congress")
    sample = {
        "bills": [
            {
                "type": "HR",
                "number": 4200,
                "title": "Digital Asset Market Structure Act",
                "latestAction": {
                    "text": "Referred to the House Committee",
                    "actionDate": "2026-03-15",
                },
                "url": "https://example/bill",
            }
        ]
    }
    _patch_http(monkeypatch, sample)
    items = await CongressAdapter().fetch()
    assert len(items) == 1
    it = items[0]
    assert it.source_type == "bill"
    assert it.entity == "HR 4200"
    assert it.category == IntelCategory.US_POLICY_BILLS
    assert it.published_at and it.published_at.year == 2026


# ─── finnhub sample ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_finnhub_maps_sample(monkeypatch):
    _enable(monkeypatch, "finnhub")
    sample = [
        {
            "headline": "Market rallies on rate cut",
            "summary": "Equities jumped after the Fed …",
            "url": "https://example/news",
            "datetime": 1_740_000_000,
            "related": "AAPL,MSFT",
        }
    ]
    _patch_http(monkeypatch, sample)
    items = await FinnhubAdapter().fetch()
    assert len(items) == 1
    it = items[0]
    assert it.source == "finnhub"
    assert it.source_type == "market_news"
    assert it.entity == "AAPL"
    assert it.category == IntelCategory.MARKET_COMPANY


# ─── cryptopanic sample ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cryptopanic_maps_sample(monkeypatch):
    _enable(monkeypatch, "cryptopanic")
    sample = {
        "results": [
            {
                "title": "Bitcoin ETF sees record inflow",
                "url": "https://example/x",
                "published_at": "2026-04-01T10:00:00Z",
                "currencies": [{"code": "BTC", "title": "Bitcoin"}],
                "source": {"title": "CoinTelegraph", "domain": "cointelegraph.com"},
            }
        ]
    }
    _patch_http(monkeypatch, sample)
    items = await CryptoPanicAdapter().fetch()
    assert len(items) == 1
    it = items[0]
    assert it.source_type == "crypto_news"
    assert it.entity == "BTC"
    assert it.category == IntelCategory.CRYPTO_STREAM


# ─── fail-soft (network / parse) ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_network_error_returns_empty(monkeypatch):
    """
    BaseAdapter._http_get 는 네트워크 에러 시 자체 try/except 로 None 반환.
    여기서는 그 계약 (None → fetch() == []) 을 검증한다.
    """
    _enable(monkeypatch, "open_dart")
    _patch_http(monkeypatch, None)
    items = await OpenDartAdapter().fetch()
    assert items == []


@pytest.mark.asyncio
async def test_unexpected_payload_shape_returns_empty(monkeypatch):
    _enable(monkeypatch, "cryptopanic")
    _patch_http(monkeypatch, {"unexpected": True})  # results 누락
    items = await CryptoPanicAdapter().fetch()
    assert items == []
