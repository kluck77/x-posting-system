"""rss_fetcher 테스트 — 실제 HTTP 요청 없이 XML 파싱만 테스트"""
import pytest
from app.services.rss_fetcher import _parse_feed, filter_new_articles, RssArticle

RSS_SAMPLE = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>테스트 피드</title>
    <item>
      <title>한국 금리 동결 결정</title>
      <link>https://example.com/article/1</link>
      <description>한국은행이 기준금리를 3.5%로 동결했다.</description>
    </item>
    <item>
      <title>환율 1400원 돌파</title>
      <link>https://example.com/article/2</link>
      <description>달러 대비 원화 환율이 1400원을 넘었다.</description>
    </item>
  </channel>
</rss>"""


class TestParseFeed:
    def test_parses_rss_articles(self):
        articles = _parse_feed(RSS_SAMPLE, "economy", "테스트")
        assert len(articles) == 2

    def test_article_fields(self):
        articles = _parse_feed(RSS_SAMPLE, "economy", "테스트")
        a = articles[0]
        assert a.title == "한국 금리 동결 결정"
        assert a.url == "https://example.com/article/1"
        assert a.category == "economy"
        assert a.source == "테스트"

    def test_invalid_xml_returns_empty(self):
        articles = _parse_feed("NOT XML AT ALL <<<", "economy", "test")
        assert articles == []

    def test_strips_html_from_title(self):
        xml = """<rss version="2.0"><channel>
        <item><title><![CDATA[<b>Bold Title</b>]]></title>
        <link>https://example.com/3</link></item>
        </channel></rss>"""
        articles = _parse_feed(xml, "economy", "test")
        assert "<b>" not in articles[0].title


class TestFilterNewArticles:
    def test_filters_seen_urls(self):
        articles = [
            RssArticle("A", "https://a.com", "", "economy", "test"),
            RssArticle("B", "https://b.com", "", "economy", "test"),
        ]
        seen = {"https://a.com"}
        new = filter_new_articles(articles, seen)
        assert len(new) == 1
        assert new[0].url == "https://b.com"

    def test_empty_seen(self):
        articles = [
            RssArticle("A", "https://a.com", "", "economy", "test"),
        ]
        new = filter_new_articles(articles, set())
        assert len(new) == 1
