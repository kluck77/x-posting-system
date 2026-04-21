"""Intel source adapters — Phase 1."""

from app.services.intel.adapters.base import BaseAdapter
from app.services.intel.adapters.congress import CongressAdapter
from app.services.intel.adapters.cryptopanic import CryptoPanicAdapter
from app.services.intel.adapters.finnhub import FinnhubAdapter
from app.services.intel.adapters.open_dart import OpenDartAdapter
from app.services.intel.adapters.coingecko import CoinGeckoAdapter
from app.services.intel.adapters.newsapi import NewsApiAdapter


def get_all_adapters() -> list[BaseAdapter]:
    """enabled/disabled 무관하게 모든 adapter 인스턴스를 반환."""
    return [
        OpenDartAdapter(),
        CongressAdapter(),
        FinnhubAdapter(),
        CryptoPanicAdapter(),
        # Phase 2 stubs (enabled=False 고정)
        NewsApiAdapter(),
        CoinGeckoAdapter(),
    ]
