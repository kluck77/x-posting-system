"""
Tavily 웹 검색 프로바이더
==========================
역할: WebSearcher — 실시간 웹 검색 & 컨텍스트 보강 (신규 역할 #6).

강점:
  - 기사 수신 즉시 최신 웹 컨텍스트 보강 → AI 초안 품질 향상
  - 무료 1,000회/월, 이후 $4/1,000회
  - search_depth="advanced": 전체 페이지 내용 포함

파이프라인에서의 역할:
  Breaking news 기사 URL/텍스트 → Tavily 검색 → 관련 최신 정보 수집
  → DraftWriter 프롬프트에 컨텍스트 주입 → 더 정확한 초안 생성

예시:
  기사: "한국은행 기준금리 동결"
  Tavily 검색: "Bank of Korea interest rate hold impact"
  결과: 최신 시장 반응, 전문가 의견 → 초안에 반영
"""

import logging
import httpx
from app.config import settings
from app.providers.base import BaseWebSearcher, WebSearchResult

logger = logging.getLogger(__name__)

TAVILY_API_URL = "https://api.tavily.com/search"


class TavilySearcher(BaseWebSearcher):
    """
    Tavily 실시간 웹 검색기.
    기사 주제에 대한 최신 웹 정보를 수집하여 AI 초안 프롬프트를 보강합니다.
    """

    async def search(
        self,
        query: str,
        max_results: int = 5,
        search_depth: str = "basic",
        include_domains: list[str] | None = None,
    ) -> WebSearchResult:
        """
        실시간 웹 검색을 수행합니다.

        Args:
            query: 검색 쿼리 (영어 권장)
            max_results: 최대 결과 수 (1-10)
            search_depth: "basic" (빠름) 또는 "advanced" (더 많은 내용)
            include_domains: 특정 도메인만 포함 (예: ["reuters.com", "bloomberg.com"])
        """
        logger.info(f"[Tavily] 검색: '{query[:60]}'")

        payload: dict = {
            "api_key":      settings.tavily_api_key,
            "query":        query,
            "max_results":  max_results,
            "search_depth": search_depth,
            "include_answer": True,
            "include_raw_content": False,
        }
        if include_domains:
            payload["include_domains"] = include_domains

        try:
            async with httpx.AsyncClient(timeout=20) as client:
                resp = await client.post(TAVILY_API_URL, json=payload)
                resp.raise_for_status()
                data = resp.json()

            results = [
                {
                    "title":   r.get("title", ""),
                    "url":     r.get("url", ""),
                    "content": r.get("content", "")[:400],
                    "score":   r.get("score", 0.0),
                }
                for r in data.get("results", [])
            ]
            summary = data.get("answer", "")

            logger.info(f"[Tavily] 결과: {len(results)}개")
            return WebSearchResult(query=query, results=results, summary=summary)

        except Exception as e:
            logger.error(f"[Tavily] 검색 오류: {e}")
            return WebSearchResult(query=query, results=[], summary="")

    async def search_korean_context(self, article_title: str) -> WebSearchResult:
        """
        한국 뉴스 기사에 대한 글로벌 반응 및 컨텍스트를 검색합니다.
        초안 작성 전 컨텍스트 보강에 사용합니다.
        """
        # 한국어 제목을 영어 검색 쿼리로 변환하는 방식 대신
        # 핵심 영어 키워드로 검색 (한국어 기사도 Tavily가 처리)
        query = f"{article_title} Korea impact market"
        return await self.search(
            query=query,
            max_results=5,
            search_depth="basic",
            include_domains=[
                "reuters.com", "bloomberg.com", "ft.com",
                "apnews.com", "cnbc.com", "wsj.com",
            ],
        )
