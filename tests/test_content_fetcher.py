"""
content_fetcher 테스트
======================
URL 판별, 트윗 ID 추출, X URL 판별 테스트.
(실제 HTTP 요청은 하지 않음)
"""

import pytest
from app.services.content_fetcher import is_url, extract_tweet_id, is_x_url


class TestIsUrl:
    def test_http_url(self):
        assert is_url("http://example.com") is True

    def test_https_url(self):
        assert is_url("https://naver.com/news/article") is True

    def test_plain_text(self):
        assert is_url("그냥 텍스트입니다") is False

    def test_empty(self):
        assert is_url("") is False

    def test_x_url(self):
        assert is_url("https://x.com/user/status/123") is True


class TestExtractTweetId:
    def test_x_status_url(self):
        url = "https://x.com/user/status/1234567890"
        assert extract_tweet_id(url) == "1234567890"

    def test_twitter_status_url(self):
        url = "https://twitter.com/user/status/9876543210"
        assert extract_tweet_id(url) == "9876543210"

    def test_no_status(self):
        assert extract_tweet_id("https://x.com/user") is None

    def test_non_url(self):
        assert extract_tweet_id("just text") is None


class TestIsXUrl:
    def test_x_com(self):
        assert is_x_url("https://x.com/user/status/123") is True

    def test_twitter_com(self):
        assert is_x_url("https://twitter.com/user/status/123") is True

    def test_naver(self):
        assert is_x_url("https://news.naver.com/article/123") is False

    def test_empty(self):
        assert is_x_url("") is False
