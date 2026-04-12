"""
뉴스 모니터
===========
1분 간격으로 RSS + Naver API를 폴링하여 신규 속보를 탐지합니다.

탐지 흐름:
  APScheduler (1분) → RSS + Naver 수집 → 중복 제거
  → 교차 확인 (4개 이상 출처 확인 시 속보 전송)
  → 수면 시간(오후 10시 ~ 오전 5시 KST): 개별 알림 없이 오버나이트 버퍼에 수집
  → 오전 5시 KST: morning_digest.py가 TOP 5 다이제스트 전송
  → (X 자동 게시 없음 — 사용자가 직접 게시)
"""

import hashlib
import json
import logging
import asyncio
import re
from datetime import datetime, timezone, timedelta
from collections import defaultdict

import httpx

from app.config import settings
from app.services.rss_fetcher import RssArticle, fetch_all_feeds, filter_new_articles
from app.services.naver_news import search_all_keywords

logger = logging.getLogger(__name__)

# KST = UTC+9
KST = timezone(timedelta(hours=9))

# 카테고리 이모지 매핑
_CAT_EMOJI = {
    "economy":  "📈",
    "politics": "🏛️",
    "policy":   "📋",
    "crypto":   "🪙",
}

# ─── 인메모리 상태 ────────────────────────────────────────────────────────────

# 이미 처리한 URL 세트
_seen_urls: set[str] = set()

# pending 기사 저장소: hash → article dict (Telegram 콜백용)
# 인메모리 상한: 운영자가 skip하지 않아도 오래된 항목이 자동 정리됨
_pending_articles: dict[str, dict] = {}
_PENDING_ARTICLES_MAX = 200

# 교차 확인 후보 스토리 클러스터
# key = story_key (normalized title words hash)
# value = {title, category, region, sources: set[str], urls: dict[source→url], first_seen}
_story_clusters: dict[str, dict] = {}

# 이미 알림을 보낸 스토리 (중복 알림 방지)
_alerted_stories: set[str] = set()

# 오버나이트 버퍼: 수면 시간 동안 수집된 기사 목록
overnight_buffer: list[dict] = []


# ─── 유틸리티 ─────────────────────────────────────────────────────────────────

def _article_hash(url: str) -> str:
    """URL → 짧은 해시 (callback_data 크기 제한 대응)."""
    return hashlib.md5(url.encode()).hexdigest()[:12]


def _is_sleep_window() -> bool:
    """현재 시각이 수면 시간(오후 10시 ~ 오전 5시 KST)인지 확인합니다."""
    hour = datetime.now(KST).hour
    return hour >= 22 or hour < 5


def _extract_keywords(title: str) -> set[str]:
    """제목에서 유의미한 단어를 추출합니다 (한국어 2글자+, 영어 4글자+)."""
    words: set[str] = set()
    # 한국어 단어 (2글자 이상)
    for w in re.findall(r"[가-힣]{2,}", title):
        words.add(w)
    # 영어 단어 (4글자 이상, 소문자)
    for w in re.findall(r"[A-Za-z]{4,}", title):
        words.add(w.lower())
    return words


def _story_key(title: str) -> str:
    """제목 키워드를 정렬·결합하여 스토리 식별 키를 생성합니다."""
    kws = sorted(_extract_keywords(title))[:6]
    return hashlib.md5(" ".join(kws).encode()).hexdigest()[:16]


def _jaccard_similarity(set_a: set, set_b: set) -> float:
    """두 집합의 Jaccard 유사도를 반환합니다."""
    if not set_a or not set_b:
        return 0.0
    inter = len(set_a & set_b)
    union = len(set_a | set_b)
    return inter / union if union else 0.0


def _find_matching_cluster(keywords: set[str], threshold: float = 0.25) -> str | None:
    """
    기존 클러스터 중 유사도가 threshold 이상인 클러스터 키를 반환합니다.
    없으면 None.
    """
    best_key, best_sim = None, 0.0
    for ck, cluster in _story_clusters.items():
        sim = _jaccard_similarity(keywords, cluster["keywords"])
        if sim > best_sim:
            best_sim, best_key = sim, ck
    if best_sim >= threshold:
        return best_key
    return None


def _cleanup_old_clusters(max_age_hours: int = 4) -> None:
    """4시간 이상 된 클러스터를 정리합니다."""
    now = datetime.now(timezone.utc)
    to_delete = [
        k for k, v in _story_clusters.items()
        if (now - v["first_seen"]).total_seconds() > max_age_hours * 3600
    ]
    for k in to_delete:
        _story_clusters.pop(k, None)
        _alerted_stories.discard(k)


# ─── Telegram 전송 ────────────────────────────────────────────────────────────

def _get_tg_url(method: str) -> str:
    return f"https://api.telegram.org/bot{settings.telegram_bot_token}/{method}"


async def _send_news_alert(cluster: dict) -> None:
    """교차 확인된 속보를 Telegram으로 전송합니다."""
    if not settings.has_telegram_config:
        logger.info(f"[MOCK 속보] ({cluster['source_count']}개 출처) {cluster['title'][:60]}")
        return

    cat_em    = _CAT_EMOJI.get(cluster["category"], "📰")
    top_url   = cluster["top_url"]       # 첫 번째 (가장 권위 있는) 출처 링크
    sources   = ", ".join(sorted(cluster["sources"]))
    ah        = _article_hash(top_url)

    region_label = "🇺🇸 US" if cluster.get("region") == "US" else "🇰🇷 KR"
    verified_tag = f"✅ {cluster['source_count']}개 교차 확인"

    # Layer 2: 소스 우선순위 레이블 (실패 시 무시)
    advisory_label = ""
    try:
        from app.services.advisory import source_advisory
        advisory_label = source_advisory({
            "title":    cluster["title"],
            "summary":  "",
            "region":   cluster.get("region", "KR"),
            "category": cluster.get("category", ""),
        })
    except Exception:
        pass

    advisory_line = f"  {advisory_label}" if advisory_label else ""

    text = (
        f"🚨 <b>속보</b> {verified_tag}{advisory_line}\n"
        f"{'─' * 28}\n"
        f"{cat_em} [{cluster['category'].upper()}] {region_label}\n\n"
        f"📰 <b>{cluster['title']}</b>\n\n"
        f"📡 출처: {sources}\n"
        f"🔗 {top_url}"
    )

    keyboard = {
        "inline_keyboard": [[
            {"text": "✍️ 초안 작성", "callback_data": f"news_draft:{ah}"},
            {"text": "⏭ 스킵",       "callback_data": f"news_skip:{ah}"},
        ]]
    }

    # 인메모리 상한 초과 시 가장 오래된 항목 제거 (Python 3.7+ dict 삽입 순서 보장)
    if len(_pending_articles) >= _PENDING_ARTICLES_MAX:
        oldest_key = next(iter(_pending_articles))
        del _pending_articles[oldest_key]

    _pending_articles[ah] = {
        "title":    cluster["title"],
        "url":      top_url,
        "summary":  "",
        "category": cluster["category"],
        "source":   sources,
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
                logger.info(f"속보 알림 전송: [{cluster['source_count']}출처] {cluster['title'][:50]}")
            else:
                logger.warning(f"알림 전송 실패 ({resp.status_code}): {resp.text[:200]}")
    except Exception as e:
        logger.error(f"알림 전송 오류: {e}")


# ─── 교차 확인 처리 ───────────────────────────────────────────────────────────

def _ingest_article(article: RssArticle) -> str | None:
    """
    기사를 클러스터에 추가합니다.

    Returns:
        교차 확인 조건을 충족한 클러스터 키 (처음 충족 시에만) 또는 None
    """
    keywords = _extract_keywords(article.title)
    if len(keywords) < 2:
        return None

    existing_key = _find_matching_cluster(keywords)

    if existing_key:
        cluster = _story_clusters[existing_key]
        cluster["sources"].add(article.source)
        cluster["urls"][article.source] = article.url
        cluster["keywords"] |= keywords
        # 소스 수 업데이트
        cluster["source_count"] = len(cluster["sources"])
    else:
        # 새 클러스터 생성
        existing_key = _story_key(article.title)
        _story_clusters[existing_key] = {
            "title":        article.title,
            "category":     article.category,
            "region":       getattr(article, "region", "KR"),
            "keywords":     keywords,
            "sources":      {article.source},
            "urls":         {article.source: article.url},
            "top_url":      article.url,   # 첫 번째 URL = top link
            "source_count": 1,
            "first_seen":   datetime.now(timezone.utc),
        }

    cluster = _story_clusters[existing_key]

    # 임계값 충족 && 아직 알림 안 보냄
    min_sources = settings.cross_verify_min_sources
    if (cluster["source_count"] >= min_sources
            and existing_key not in _alerted_stories):
        _alerted_stories.add(existing_key)
        return existing_key

    return None


# ─── 퍼블릭 접근자 ───────────────────────────────────────────────────────────

def get_pending_article(article_hash: str) -> dict | None:
    return _pending_articles.get(article_hash)


def remove_pending_article(article_hash: str) -> None:
    _pending_articles.pop(article_hash, None)


def get_overnight_buffer() -> list[dict]:
    return list(overnight_buffer)


def clear_overnight_buffer() -> None:
    overnight_buffer.clear()


# ─── 모니터 메인 사이클 ───────────────────────────────────────────────────────

async def run_monitor_cycle() -> int:
    """
    1회 모니터 사이클 실행.

    수면 시간(22:00~05:00 KST):
      - 개별 속보 알림 없음
      - 오버나이트 버퍼에만 추가

    깨어 있는 시간:
      - 4개 이상 출처 교차 확인 후 속보 알림 전송

    Returns:
        발견된 신규 기사 수
    """
    sleeping = _is_sleep_window()
    logger.debug(
        f"[Monitor] 사이클 시작 {datetime.now(KST).strftime('%H:%M KST')} "
        f"{'(수면 모드)' if sleeping else ''}"
    )

    try:
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

        new_articles = filter_new_articles(all_articles, _seen_urls)
        if not new_articles:
            logger.debug("[Monitor] 신규 기사 없음")
            return 0

        # seen_urls 업데이트
        for a in new_articles:
            _seen_urls.add(a.url)

        # 오래된 클러스터 정리
        _cleanup_old_clusters()

        alerts_sent = 0
        _db_dup_count = 0
        _pipeline_count = 0
        for article in new_articles:
            # 오버나이트 버퍼 수집 (수면 시간 여부 무관하게)
            if sleeping:
                overnight_buffer.append({
                    "title":    article.title,
                    "url":      article.url,
                    "summary":  article.summary,
                    "category": article.category,
                    "source":   article.source,
                    "region":   getattr(article, "region", "KR"),
                    "added_at": datetime.now(KST).isoformat(),
                })

            # 교차 확인 클러스터 업데이트 (기존 유지)
            ready_key = _ingest_article(article)

            # [NEW] 개별 기사를 full_pipeline 으로 전달 (BREAKING/CANDIDATE 만)
            try:
                from app.services.breaking_classifier import classify_article
                _br = classify_article(
                    title=article.title,
                    body=article.summary or "",
                    url=article.url,
                )
                if _br.classification in ("BREAKING_NOW", "CANDIDATE"):
                    # URL 사전 중복 체크 (DB) — Orchestrator 생성 전에 걸러냄
                    from app.db import SessionLocal
                    from app.models.content import SourceItem
                    _pre_db = SessionLocal()
                    try:
                        _url_exists = _pre_db.query(SourceItem.id).filter(
                            SourceItem.url == article.url.strip()
                        ).first() is not None
                    finally:
                        _pre_db.close()
                    if _url_exists:
                        _db_dup_count += 1
                        continue

                    _pipeline_count += 1
                    from app.models.content import SourceItemCreate
                    from app.orchestrator import Orchestrator
                    from app.services.text_cleaner import clean_article_text
                    _raw_text = article.summary or article.title
                    _payload = SourceItemCreate(
                        title=article.title,
                        source_text=clean_article_text(_raw_text),
                        url=article.url,
                        source_type="naver_auto",
                        language="ko",
                    )
                    _orch = Orchestrator()
                    try:
                        _result = await _orch.full_pipeline(_payload)
                        logger.info(
                            f"[Monitor→Pipeline] {article.title[:40]}: "
                            f"{_br.classification}/{_br.topic_domain}"
                        )
                    finally:
                        _orch.close()
            except Exception as _e:
                logger.debug(f"[Monitor→Pipeline] fail-open: {_e}")

            # [DISABLED] old direct telegram alert — full_pipeline 이 대체
            # if not sleeping and ready_key:
            #     cluster = _story_clusters.get(ready_key)
            #     if cluster and alerts_sent < settings.monitor_max_alerts_per_run:
            #         await _send_news_alert(cluster)
            #         await asyncio.sleep(0.5)
            #         alerts_sent += 1

        if not sleeping and alerts_sent > 0:
            logger.info(f"[Monitor] 속보 전송: {alerts_sent}건")
        elif sleeping:
            logger.debug(f"[Monitor] 수면 모드 — 버퍼 누적: {len(overnight_buffer)}건")

        # 사이클 요약 로그
        if _db_dup_count > 0 or _pipeline_count > 0:
            logger.info(
                f"[Monitor] 사이클: 수집={len(all_articles)} "
                f"신규={len(new_articles)} DB중복={_db_dup_count} "
                f"파이프라인={_pipeline_count}"
            )

        return len(new_articles)

    except Exception as e:
        logger.error(f"[Monitor] 사이클 오류: {e}", exc_info=True)
        return 0
