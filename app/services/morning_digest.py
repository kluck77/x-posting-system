"""
모닝 다이제스트
===============
오후 10시 ~ 오전 5시 KST(수면 시간) 동안 수집된 뉴스 중
중요도 TOP 5를 선별하여 오전 5시 KST에 Telegram으로 요약 전송합니다.

중요도 기준:
  1. 교차 출처 수 (몇 개 매체가 보도했는지)
  2. 중요 키워드 매칭 (금리, 전쟁, 규제, 환율, Fed, Bitcoin 등)
  3. 글로벌 vs 로컬 가중치
"""

import asyncio
import logging
from datetime import datetime, timezone, timedelta
from collections import defaultdict

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))

# ─── 중요도 키워드 ────────────────────────────────────────────────────────────

_HIGH_IMPORTANCE: list[str] = [
    # 금융/경제
    "금리", "기준금리", "fed", "연준", "interest rate", "inflation", "deflation",
    "recession", "gdp", "경기침체", "부도", "default", "bankruptcy", "bailout",
    "환율", "달러", "엔화", "yuan", "currency", "devaluation",
    # 크립토
    "bitcoin", "btc", "ethereum", "crypto", "blockchain", "sec", "etf",
    "가상화폐", "코인", "규제", "승인", "ban", "裁",
    # 지정학
    "전쟁", "war", "conflict", "sanctions", "tariff", "관세",
    "north korea", "북한", "china", "중국", "russia", "러시아",
    "ukraine", "middle east", "iran",
    # 정책/정치
    "대통령", "국회", "법안", "president", "congress", "senate",
    "election", "선거", "emergency", "긴급", "martial law", "계엄",
    # 시장 충격
    "crash", "폭락", "surge", "급등", "급락", "circuit breaker",
    "ipo", "merger", "acquisition", "인수", "파산",
]

_MEDIUM_IMPORTANCE: list[str] = [
    "bank", "은행", "stock", "주식", "bond", "채권", "oil", "유가",
    "tech", "ai", "semiconductor", "반도체", "supply chain",
    "trade", "무역", "export", "import", "수출", "수입",
]


def _importance_score(article: dict) -> int:
    """기사의 중요도 점수를 계산합니다 (0~100)."""
    title_lower = (article.get("title", "") + " " + article.get("summary", "")).lower()
    score = 0

    # 고중요도 키워드
    for kw in _HIGH_IMPORTANCE:
        if kw.lower() in title_lower:
            score += 15
            break  # 카테고리당 1회만 가산

    # 중간 중요도 키워드 (최대 2개)
    matches = sum(1 for kw in _MEDIUM_IMPORTANCE if kw.lower() in title_lower)
    score += min(matches, 2) * 5

    # 미국 뉴스 보너스 (글로벌 임팩트 가중치)
    if article.get("region") == "US":
        score += 10

    # 크립토 카테고리 보너스 (팔로워 관심)
    if article.get("category") == "crypto":
        score += 8

    return min(score, 100)


# ─── 스토리 클러스터링 ────────────────────────────────────────────────────────

def _deduplicate_and_rank(articles: list[dict]) -> list[dict]:
    """
    유사 기사를 그룹화하고 중요도 순으로 정렬합니다.

    같은 스토리를 여러 매체가 다루면 coverage_count가 올라가
    중요도에 가산됩니다.
    """
    import re, hashlib

    def extract_kws(title: str) -> frozenset[str]:
        kw = set()
        for w in re.findall(r"[가-힣]{2,}", title):
            kw.add(w)
        for w in re.findall(r"[A-Za-z]{4,}", title):
            kw.add(w.lower())
        return frozenset(kw)

    def jaccard(a: frozenset, b: frozenset) -> float:
        i = len(a & b)
        u = len(a | b)
        return i / u if u else 0.0

    clusters: list[dict] = []  # {representative, sources, score, count}

    for art in articles:
        kws = extract_kws(art.get("title", ""))
        matched = False
        for cl in clusters:
            if jaccard(kws, cl["keywords"]) >= 0.25:
                cl["count"] += 1
                cl["sources"].add(art.get("source", "?"))
                # 더 높은 점수 기사로 대표 교체
                if art.get("_score", 0) > cl["representative"].get("_score", 0):
                    cl["representative"] = art
                matched = True
                break
        if not matched:
            clusters.append({
                "representative": art,
                "keywords":       kws,
                "sources":        {art.get("source", "?")},
                "count":          1,
            })

    # 최종 점수 = 중요도 점수 + 교차 출처 보너스
    result = []
    for cl in clusters:
        rep = dict(cl["representative"])
        coverage_bonus = min(cl["count"] - 1, 5) * 8  # 최대 +40
        rep["_final_score"] = rep.get("_score", 0) + coverage_bonus
        rep["_coverage_count"] = cl["count"]
        rep["_all_sources"] = ", ".join(sorted(cl["sources"]))
        result.append(rep)

    result.sort(key=lambda x: x["_final_score"], reverse=True)
    return result


# ─── AI 다이제스트 생성 ───────────────────────────────────────────────────────

async def _call_ai(system_prompt: str, user_prompt: str) -> str | None:
    """Claude 또는 OpenAI로 단순 텍스트 응답을 요청합니다."""
    if settings.has_anthropic:
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "x-api-key": settings.anthropic_api_key,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                    json={
                        "model": "claude-haiku-4-5-20251001",
                        "max_tokens": 700,
                        "system": system_prompt,
                        "messages": [{"role": "user", "content": user_prompt}],
                    },
                )
                resp.raise_for_status()
                return resp.json()["content"][0]["text"]
        except Exception as e:
            logger.warning(f"Claude 다이제스트 호출 오류: {e}")

    if settings.has_openai:
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {settings.openai_api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": "gpt-4o-mini",
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt},
                        ],
                        "max_tokens": 700,
                        "temperature": 0.4,
                    },
                )
                resp.raise_for_status()
                return resp.json()["choices"][0]["message"]["content"]
        except Exception as e:
            logger.warning(f"OpenAI 다이제스트 호출 오류: {e}")

    return None


async def _generate_digest_tweets(top5: list[dict]) -> list[str]:
    """
    TOP 5 기사 → 트위터 스레드 형식으로 생성합니다.
    각 기사가 독립적인 트윗 초안이 됩니다 (복사 붙여넣기 가능).
    """
    articles_text = ""
    for i, art in enumerate(top5, 1):
        articles_text += (
            f"{i}. [{art.get('category','').upper()}] {art.get('region','')}\n"
            f"   제목: {art.get('title','')}\n"
            f"   출처: {art.get('_all_sources', art.get('source',''))}\n\n"
        )

    system_prompt = (
        "당신은 X 계정 @cheesesvav의 초안 작성자입니다.\n"
        "계정 정체성: '헤드라인 너머: 한국이 실제로 어떻게 돌아가고, 느끼고, 변하는지.'\n\n"
        "작업: 오버나이트 뉴스를 바로 게시 가능한 X 트윗 초안으로 변환하라.\n\n"
        "각 뉴스마다 트윗 1개(최대 270자)를 아래 공식으로 작성:\n"
        "- 숫자, 모순, 타이밍 신호로 시작 ('한국은' 또는 '한국의'로 시작 금지)\n"
        "- 구체적 팩트 또는 숫자 1개\n"
        "- 해석 또는 함의 한 줄\n"
        "- 짧은 CTA로 마무리\n"
        "각 트윗은 독립적이어야 한다. 한국어로 작성. 해석 중심. 애매한 표현 금지."
    )

    user_prompt = (
        f"아래 {len(top5)}개 오버나이트 뉴스를 각각 트윗 초안으로 변환하라.\n\n"
        f"{articles_text}\n"
        f"트윗 문자열의 JSON 배열로 반환:\n"
        f'["트윗 1 (최대 270자)", "트윗 2", ...]'
    )

    result = await _call_ai(system_prompt, user_prompt)
    if result:
        try:
            import json, re
            # JSON 배열 추출
            match = re.search(r'\[.*\]', result, re.DOTALL)
            if match:
                tweets = json.loads(match.group())
                if isinstance(tweets, list) and tweets:
                    return [str(t)[:280] for t in tweets]
        except Exception as e:
            logger.warning(f"다이제스트 트윗 파싱 오류: {e}")

    # AI 없거나 파싱 실패 시 폴백 — 제목을 그대로 트윗 초안으로
    tweets = []
    for art in top5:
        title = art.get('title', '(제목 없음)')
        region = "🇺🇸" if art.get('region') == 'US' else "🇰🇷"
        tweets.append(f"{region} {title[:240]}\n\n[원문 링크 아래]")
    return tweets


# ─── Telegram 전송 ────────────────────────────────────────────────────────────

def _get_tg_url(method: str) -> str:
    return f"https://api.telegram.org/bot{settings.telegram_bot_token}/{method}"


async def _send_tg_message(text: str, disable_preview: bool = True) -> bool:
    """단일 Telegram 메시지 전송."""
    payload = {
        "chat_id":    settings.telegram_chat_id,
        "text":       text[:4000],
        "parse_mode": "HTML",
        "disable_web_page_preview": disable_preview,
    }
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(_get_tg_url("sendMessage"), data=payload)
            return resp.status_code == 200
    except Exception as e:
        logger.error(f"Telegram 전송 오류: {e}")
        return False


async def _send_digest(tweets: list[str], top5: list[dict]) -> None:
    """
    모닝 다이제스트를 Telegram으로 전송합니다.

    형식: 헤더 → 각 트윗 초안(번호 포함) → 원문 링크 목록
    각 트윗 초안은 복사 붙여넣기 가능한 형태로 전달.
    """
    if not settings.has_telegram_config:
        for i, t in enumerate(tweets, 1):
            logger.info(f"[MOCK 다이제스트 {i}/{len(tweets)}] {t[:80]}")
        return

    now_kst = datetime.now(KST).strftime("%m/%d %H:%M")

    # 헤더 메시지
    header = (
        f"🌅 <b>오버나이트 TOP {len(top5)} — {now_kst} KST</b>\n"
        f"<i>헤드라인 너머: 한국이 실제로 어떻게 돌아가고, 느끼고, 변하는지.</i>\n"
        f"{'─' * 30}\n"
        f"아래 각 트윗 초안을 복사해서 X에 바로 게시하세요 👇"
    )
    await _send_tg_message(header)
    await asyncio.sleep(0.5)

    # 각 트윗 초안 개별 전송
    total = len(tweets)
    for i, (tweet, art) in enumerate(zip(tweets, top5), 1):
        region = "🇺🇸" if art.get('region') == 'US' else "🇰🇷"
        cat_em = {"economy": "📈", "crypto": "🪙", "politics": "🏛️", "community": "💬"}.get(
            art.get('category', ''), "📰"
        )
        msg = (
            f"{cat_em} <b>[{i}/{total}]</b> {region}\n"
            f"{'─' * 20}\n"
            f"<code>{tweet}</code>\n\n"
            f"🔗 {art.get('url','')}"
        )
        await _send_tg_message(msg)
        await asyncio.sleep(0.3)

    logger.info(f"모닝 다이제스트 전송 완료: {total}개 트윗 초안")


# ─── 메인 퍼블릭 함수 ────────────────────────────────────────────────────────

async def run_morning_digest() -> None:
    """
    오전 5시 KST에 APScheduler가 호출하는 메인 함수.
    오버나이트 버퍼에서 TOP 5를 선별하여 Telegram으로 전송합니다.
    """
    from app.services.news_monitor import get_overnight_buffer, clear_overnight_buffer

    buffer = get_overnight_buffer()
    logger.info(f"[Digest] 오버나이트 버퍼: {len(buffer)}건")

    if not buffer:
        logger.info("[Digest] 수집된 뉴스 없음 — 다이제스트 건너뜀")
        return

    # 중요도 점수 계산
    for art in buffer:
        art["_score"] = _importance_score(art)

    # 중복 제거 + 랭킹
    ranked = _deduplicate_and_rank(buffer)
    top_n = settings.digest_top_n
    top5 = ranked[:top_n]

    logger.info(
        f"[Digest] TOP {top_n} 선별 완료: "
        + ", ".join(a.get('title', '')[:30] for a in top5)
    )

    # AI 트윗 초안 생성 (각 기사 → 독립 트윗 초안)
    tweets = await _generate_digest_tweets(top5)

    # Telegram 전송 (각 트윗 초안 개별 메시지)
    await _send_digest(tweets, top5)

    # 버퍼 초기화
    clear_overnight_buffer()
    logger.info("[Digest] 오버나이트 버퍼 초기화 완료")
