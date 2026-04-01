"""
뉴스 모니터
===========
1분 간격으로 RSS + Naver API를 폴링하여 신규 속보를 탐지합니다.
신규 기사 발견 시 Telegram으로 알림을 전송합니다.
(X 자동 게시 없음 — 사용자가 직접 게시)

탐지 흐름:
  APScheduler (1분) → RSS + Naver 수집 → 중복 제거
  → 신규 기사 → Telegram 속보 알림 ([✍️ 초안 작성] [⏭ 스킵] 버튼)
  → 사용자가 [✍️] 클릭 → AI 파이프라인 → 초안 텍스트 Telegram 전달
"""

import hashlib
import json
import logging
import asyncio
from datetime import datetime, timezone

import httpx

from app.config import settings
from app.services.rss_fetcher import RssArticle, fetch_all_feeds, filter_new_articles
from app.services.naver_news import search_all_keywords

logger = logging.getLogger(__name__)

# 카테고리 이모지 매핑
_CAT_EMOJI = {
    "economy":  "📈",
    "politics": "🏛️",
    "policy":   "📋",
    "crypto":   "🪙",
}

# 인메모리 URL 세트 (재시작 시 초기화 — 의도적, 중복 DB 체크로 보완)
_seen_urls: set[str] = set()


def _article_hash(url: str) -> str:
    """URL → 짧은 해시 (callback_data 크기 제한 대응)."""
    return hashlib.md5(url.encode()).hexdigest()[:12]


# ─── Telegram 전송 ────────────────────────────────────────────────────────────

def _get_tg_url(method: str) -> str:
    return f"https://api.telegram.org/bot{settings.telegram_bot_token}/{method}"


async def _send_news_alert(article: RssArticle) -> None:
    """Telegram으로 속보 알림 카드를 전송합니다."""
    if not settings.has_telegram_config:
        logger.info(f"[MOCK 알림] {article.title[:60]}")
        return

    cat_em  = _CAT_EMOJI.get(article.category, "📰")
    ah      = _article_hash(article.url)
    summary = article.summary[:200] if article.summary else ""

    text = (
        f"🚨 <b>속보 감지!</b>\n"
        f"{'─' * 28}\n"
        f"{cat_em} [{article.category.upper()}] {article.source}\n\n"
        f"📰 <b>{article.title}</b>\n"
    )
    if summary:
        text += f"\n{summary}...\n"
    text += f"\n🔗 {article.url}"

    keyboard = {
        "inline_keyboard": [[
            {"text": "✍️ 초안 작성", "callback_data": f"news_draft:{ah}"},
            {"text": "⏭ 스킵",      "callback_data": f"news_skip:{ah}"},
        ]]
    }

    # 기사 정보를 나중에 콜백에서 복원할 수 있도록 별도 메시지로 저장
    # (Telegram에는 callback_data 64바이트 제한 있음 → 해시로 참조)
    _pending_articles[ah] = {
        "title":    article.title,
        "url":      article.url,
        "summary":  article.summary,
        "category": article.category,
        "source":   article.source,
    }

    payload = {
        "chat_id":      settings.telegram_chat_id,
        "text":         text,
        "parse_mode":   "HTML",
        "reply_markup": json.dumps(keyboard),
        "disable_web_page_preview": True,
    }

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(_get_tg_url("sendMessage"), data=payload)
            if resp.status_code == 200:
                logger.info(f"속보 알림 전송: {article.title[:50]}")
            else:
                logger.warning(f"알림 전송 실패 ({resp.status_code}): {resp.text[:200]}")
    except Exception as e:
        logger.error(f"알림 전송 오류: {e}")


# 인메모리 pending 기사 저장소 (article_hash → article dict)
_pending_articles: dict[str, dict] = {}


def get_pending_article(article_hash: str) -> dict | None:
    """콜백 핸들러에서 기사 정보를 복원합니다."""
    return _pending_articles.get(article_hash)


def remove_pending_article(article_hash: str) -> None:
    _pending_articles.pop(article_hash, None)


# ─── 모니터 사이클 ────────────────────────────────────────────────────────────

async def run_monitor_cycle() -> int:
    """
    1회 모니터 사이클 실행.

    Returns:
        발견된 신규 기사 수
    """
    logger.debug(f"[Monitor] 사이클 시작: {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}")

    try:
        # RSS + Naver 병렬 수집
        rss_articles, naver_articles = await asyncio.gather(
            fetch_all_feeds(),
            search_all_keywords(),
            return_exceptions=True,
        )
        all_articles: list[RssArticle] = []
        if isinstance(rss_articles, list):
            all_articles.extend(rss_articles)
        if isinstance(naver_articles, list):
            all_articles.extend(naver_articles)

        # URL 중복 제거 (인메모리 세트)
        new_articles = filter_new_articles(all_articles, _seen_urls)

        # DB 중복 체크 (이미 수집된 URL 제외)
        try:
            from app.db import get_db
            from app.services.source_service import SourceService
            db = get_db()
            try:
                svc = SourceService(db)
                new_articles = [
                    a for a in new_articles
                    if not svc.is_duplicate_url(a.url)
                ]
            finally:
                db.close()
        except Exception as e:
            logger.warning(f"DB 중복 체크 실패 (건너뜀): {e}")

        if not new_articles:
            logger.debug("[Monitor] 신규 기사 없음")
            return 0

        # 한 사이클당 최대 3개 알림 (스팸 방지)
        max_alerts = settings.monitor_max_alerts_per_run
        to_alert = new_articles[:max_alerts]

        for article in to_alert:
            _seen_urls.add(article.url)
            await _send_news_alert(article)
            await asyncio.sleep(0.5)  # Telegram 레이트 리밋 방지

        logger.info(f"[Monitor] 알림 전송: {len(to_alert)}건 (발견: {len(new_articles)}건)")
        return len(to_alert)

    except Exception as e:
        logger.error(f"[Monitor] 사이클 오류: {e}", exc_info=True)
        return 0
