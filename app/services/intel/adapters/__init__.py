"""Intel source adapters.

활성 adapter (운영 중):
  - OpenDart (DART 전자공시)
  - Finnhub (마켓/기업 뉴스)

기존 dormant adapter 4개 (congress/cryptopanic/newsapi/coingecko) 는
Phase-final 에서 제거됐음. 신규 소스 (polymarket) 는 adapter 경로가
아니라 app/sources/polymarket_fetcher.py 로 별도 관리.
"""

from app.services.intel.adapters.base import BaseAdapter
from app.services.intel.adapters.finnhub import FinnhubAdapter
from app.services.intel.adapters.open_dart import OpenDartAdapter


def get_all_adapters() -> list[BaseAdapter]:
    """enabled/disabled 무관하게 활성 adapter 인스턴스 전부 반환."""
    return [
        OpenDartAdapter(),
        FinnhubAdapter(),
    ]
