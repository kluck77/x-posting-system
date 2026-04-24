"""YouTube URL → 발언 추출 → 파이프라인 투입.

자막 추출:
  1차 youtube-transcript-api (설치돼 있으면)
  2차 Gemini 2.5 Flash (file_data + youtube URI) fallback

발언 추출 + 스코어링: Gemini 로 JSON 반환.

규칙:
  - importance_score >= 55 + is_risky=False 만 저장
  - 영상당 최대 5개 (30초 이내 인접 발언 dedup)
  - quote_hash = md5(video_id + timestamp_sec) 기준 DB dedup
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import sqlite3
import time
from dataclasses import dataclass, field

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


def _sqlite_path() -> str:
    url = settings.database_url or ""
    m = re.match(r"sqlite:///(.+)", url)
    return m.group(1) if m else "./x_poster.db"


def _loose_json_array(raw: str) -> list | None:
    """Gemini 가 깨뜨린 JSON 에서 배열 복구. 실패 시 None."""
    if not raw:
        return None
    try:
        val = json.loads(raw)
        return val if isinstance(val, list) else None
    except Exception:
        pass
    # 배열 시작/끝 탐지
    i = raw.find("[")
    if i < 0:
        return None
    # 마지막 닫는 괄호까지 잘라내면서 점차 줄여 재시도
    for j in range(len(raw) - 1, i, -1):
        if raw[j] == "]":
            try:
                val = json.loads(raw[i : j + 1])
                if isinstance(val, list):
                    return val
            except Exception:
                continue
    # 항목별 파싱 복구 — 각 {...} 블록만 개별 로드
    items: list = []
    depth = 0
    start = -1
    for k in range(i, len(raw)):
        c = raw[k]
        if c == "{":
            if depth == 0:
                start = k
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0 and start >= 0:
                try:
                    items.append(json.loads(raw[start : k + 1]))
                except Exception:
                    pass
                start = -1
    return items or None


def _loose_json_object(raw: str) -> dict | None:
    """Gemini 가 깨뜨린 JSON 에서 객체 복구. 실패 시 None."""
    if not raw:
        return None
    try:
        val = json.loads(raw)
        return val if isinstance(val, dict) else None
    except Exception:
        pass
    i = raw.find("{")
    if i < 0:
        return None
    for j in range(len(raw) - 1, i, -1):
        if raw[j] == "}":
            try:
                val = json.loads(raw[i : j + 1])
                if isinstance(val, dict):
                    return val
            except Exception:
                continue
    return None


async def _gemini_post_with_retry(
    client: httpx.AsyncClient,
    url: str,
    payload: dict,
    *,
    max_attempts: int = 3,
) -> httpx.Response:
    """Gemini 호출 — 503/429/5xx 자동 재시도 (1s → 3s → 7s)."""
    backoff = [1.0, 3.0, 7.0]
    last: httpx.Response | None = None
    for attempt in range(max_attempts):
        resp = await client.post(url, json=payload)
        last = resp
        if resp.status_code < 500 and resp.status_code != 429:
            return resp
        wait = backoff[min(attempt, len(backoff) - 1)]
        logger.info(
            f"[YT] Gemini {resp.status_code} retry {attempt + 1}/{max_attempts} "
            f"after {wait}s"
        )
        await asyncio.sleep(wait)
    return last  # type: ignore


HIGH_VALUE_KW = re.compile(
    r"fed|연준|기준금리|한은|인플레이션|cpi|ppi|고용|실업률"
    r"|비트코인|btc|이더리움|eth|sec|etf|폴리마켓"
    r"|경기침체|recession|달러|원화|환율|금리|채권"
    r"|반도체|엔비디아|삼성|하이닉스|hbm|tsmc"
    r"|부동산|전세|금통위|fomc",
    re.IGNORECASE,
)

RISK_KW = re.compile(r"욕설|명예훼손|허위|개인정보|사생활")


def _format_full_transcript(snippets: list[dict]) -> str:
    """전체 자막을 타임스탬프 포함 텍스트로 변환."""
    lines = []
    for s in snippets:
        sec = int(s.get("start", 0) or 0)
        mm, ss = sec // 60, sec % 60
        lines.append(f"[{mm:02d}:{ss:02d}] {s.get('text', '')}")
    return "\n".join(lines)


def _filter_intro(snippets: list[dict]) -> list[dict]:
    """첫 180초(3분) 스니펫 제외 — 인트로·티저 차단."""
    return [s for s in snippets if float(s.get("start", 0) or 0) >= 180]


@dataclass
class YoutubeQuote:
    text:              str
    speaker:           str
    channel:           str
    video_id:          str
    video_title:       str
    timestamp:         str
    timestamp_sec:     int
    topic_tag:         str
    importance_score:  int
    context_before:    str = ""
    context_after:     str = ""
    url:               str = ""
    is_risky:          bool = False
    extracted_at:      float = field(default_factory=time.time)

    def to_news_format(self) -> dict:
        """기존 파이프라인에 주입할 뉴스 포맷 (맥락·영상 논지 포함)."""
        return {
            "title": f"[유튜브 발언] {self.speaker}: {self.text[:50]}",
            "body": (
                f"[발언 원문]\n"
                f'"{self.text}"\n\n'
                f"[발언자] {self.speaker} · {self.channel} · {self.timestamp}\n\n"
                f"[앞 맥락]\n{self.context_before}\n\n"
                f"[뒤 맥락]\n{self.context_after}\n\n"
                f"[출처] {self.url}\n\n"
                f"위 발언을 중심으로 포스트를 작성하세요.\n"
                f"발언 원문은 큰따옴표로 인용하고 "
                f"서사는 앞뒤 맥락을 활용하세요."
            ),
            "url": self.url,
            "source": "youtube",
            "category": self.topic_tag,
            "score": self.importance_score,
            "speaker": self.speaker,
            "timestamp": self.timestamp,
        }


# ─── URL 파싱 ────────────────────────────────────────────────────────
def extract_video_id(url: str) -> str | None:
    patterns = [
        r"(?:youtube\.com/watch\?v=|youtu\.be/)([^&\n?#]+)",
        r"youtube\.com/shorts/([^&\n?#]+)",
    ]
    for p in patterns:
        m = re.search(p, url or "")
        if m:
            return m.group(1)
    return None


def is_youtube_url(url: str) -> bool:
    return bool(extract_video_id(url))


# ─── 자막 추출 ────────────────────────────────────────────────────────
async def fetch_transcript(video_id: str) -> list[dict]:
    """1차 youtube-transcript-api → 실패 시 2차 Gemini fallback."""
    # 1차
    try:
        from youtube_transcript_api import YouTubeTranscriptApi  # type: ignore
        ytt = YouTubeTranscriptApi()
        fetched = ytt.fetch(video_id, languages=["ko", "en"])
        snippets = [
            {
                "start":    float(getattr(s, "start", 0.0) or 0.0),
                "duration": float(getattr(s, "duration", 0.0) or 0.0),
                "text":     str(getattr(s, "text", "") or ""),
            }
            for s in fetched
        ]
        logger.info(f"[YT] 자막 추출 성공 ({len(snippets)} snippets)")
        return snippets
    except Exception as e:
        logger.warning(f"[YT] youtube-transcript-api 실패: {e}")

    return await _gemini_transcript_fallback(video_id)


async def _gemini_transcript_fallback(video_id: str) -> list[dict]:
    """Gemini 2.5 Flash 에 youtube URI 직접 전달해서 발언 추출."""
    api_key = settings.gemini_api_key
    if not api_key:
        return []
    url = f"https://www.youtube.com/watch?v={video_id}"
    prompt = (
        "이 유튜브 영상의 자막을 타임스탬프(초) 단위로 추출해 "
        "JSON 배열로만 반환 (설명·코멘트 금지): "
        '[{"start": 정수초, "text": "한 문장"}, ...]. '
        "최대 200개 항목까지. 발언 전체가 아닌 주요 문장만 남겨도 됨."
    )
    payload = {
        "contents": [{
            "parts": [
                {"text": prompt},
                {"file_data": {"mime_type": "video/youtube", "file_uri": url}},
            ],
        }],
        "generationConfig": {
            "temperature": 0.0,
            "maxOutputTokens": 6000,
            "responseMimeType": "application/json",
        },
    }
    try:
        async with httpx.AsyncClient(timeout=300.0) as client:
            resp = await _gemini_post_with_retry(
                client,
                "https://generativelanguage.googleapis.com/v1beta/"
                f"models/gemini-2.5-flash:generateContent?key={api_key}",
                payload,
            )
            if resp.status_code != 200:
                logger.warning(
                    f"[YT] Gemini fallback HTTP {resp.status_code}: "
                    f"{resp.text[:500]}"
                )
                return []
            body = resp.json()
            try:
                text = body["candidates"][0]["content"]["parts"][0]["text"]
            except (KeyError, IndexError, TypeError) as ke:
                logger.warning(
                    f"[YT] Gemini fallback 응답 구조 이상 ({type(ke).__name__}): "
                    f"{json.dumps(body)[:500]}"
                )
                return []
            text = text.strip().strip("```json").strip("```").strip()
            data = _loose_json_array(text)
            if data is None:
                logger.warning(
                    f"[YT] Gemini fallback JSON 파싱 실패 — 원문 앞 500자: "
                    f"{text[:500]!r}"
                )
                return []
            logger.info(f"[YT] Gemini fallback 성공 ({len(data)} snippets)")
            return [
                {
                    "start":    float(d.get("start", 0) or 0),
                    "duration": 3.0,
                    "text":     str(d.get("text", "") or ""),
                }
                for d in (data or [])
            ]
    except Exception as e:
        logger.warning(
            f"[YT] Gemini fallback 실패 ({type(e).__name__}): {e!r}"
        )
        return []


# ─── 발언 추출 (Gemini) ───────────────────────────────────────────────
EXTRACTION_PROMPT = """당신은 한국 매크로·크립토 전문 편집자입니다.
아래는 유튜브 영상의 전체 자막입니다.

다음 2단계로 처리하세요:

## Step 1: 영상 전체 논지 파악
영상 전체를 읽고 핵심 주장 1~2개를 파악합니다.
발언자가 영상 전체에서 말하려는 핵심이 무엇인지 정리합니다.

## Step 2: 발언 추출
핵심 논지를 뒷받침하는 발언 3~5개를 추출합니다.

발언 선택 기준 (4개 이상 충족):
1. 맥락 없이도 이해 가능
2. 첫 10단어에 훅이 있음
3. 반박 가능한 주장
4. 숫자·비교·예측 포함
5. 단정·비유·격언 포함
6. 핵심 논지와 직접 연결됨

제외:
- 첫 3분 발언 (인트로·티저)
- 투자 권유 면책 발언
- 인사말·소개
- 의미 없는 추임새

is_risky 는 다음 중 하나에 해당할 때만 true (아니면 false):
- 특정 실명 인물·기업 비방·명예훼손
- 욕설·혐오·성적 표현
- 개인정보·사생활 노출
- 검증 불가 허위 단정
※ 의견·예측·단정·시장 전망은 is_risky=false 가 기본.

## 출력 형식
JSON만 반환 (다른 텍스트 절대 금지):
{
  "video_summary": "영상 전체 핵심 논지 2~3문장 한국어 요약",
  "main_argument": "발언자의 핵심 주장 1문장",
  "speaker": "발언자 이름 (자막에서 추정, 모르면 '발언자 미확인')",
  "video_title": "영상 제목 추정 또는 빈 문자열",
  "quotes": [
    {
      "text": "발언 원문 그대로 (80자 이내)",
      "timestamp_sec": 734,
      "timestamp": "12:14",
      "topic_tag": "macro|crypto|policy|semi|geo|real_estate|equity",
      "importance_score": 0-100,
      "context_before": "이 발언이 나온 앞 맥락 3~5문장",
      "context_after": "이 발언 이후 전개 3~5문장",
      "why_important": "이 발언이 핵심 논지와 어떻게 연결되는가 1문장",
      "has_number": true,
      "has_prediction": true,
      "is_contrarian": false,
      "is_risky": false
    }
  ]
}"""


async def extract_quotes(
    snippets: list[dict],
    video_meta: dict,
) -> list[YoutubeQuote]:
    """Gemini 로 발언 단위 추출 + 스코어링. 전체 자막 사용."""
    if not snippets:
        return []
    api_key = settings.gemini_api_key
    if not api_key:
        return []

    # 전체 자막 (길이 제한 없음) — 2-step 프롬프트가 영상 전체 논지 파악 요구
    transcript_text = _format_full_transcript(snippets)

    payload = {
        "systemInstruction": {"parts": [{"text": EXTRACTION_PROMPT}]},
        "contents": [{
            "parts": [{
                "text": (
                    f"채널: {video_meta.get('channel', '알 수 없음')}\n"
                    f"영상 URL: {video_meta.get('url', '')}\n\n"
                    f"전체 자막:\n{transcript_text}"
                ),
            }],
        }],
        "generationConfig": {
            "temperature": 0.0,
            "maxOutputTokens": 4000,
            "responseMimeType": "application/json",
        },
    }

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await _gemini_post_with_retry(
                client,
                "https://generativelanguage.googleapis.com/v1beta/"
                f"models/gemini-2.5-flash:generateContent?key={api_key}",
                payload,
            )
            resp.raise_for_status()
            raw = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
            raw = raw.strip().strip("```json").strip("```").strip()
            data = _loose_json_object(raw)
            if data is None:
                logger.warning(
                    f"[YT] 발언 추출 JSON 파싱 실패 — 원문 앞 500자: {raw[:500]!r}"
                )
                return []
    except Exception as e:
        logger.warning(f"[YT] 발언 추출 실패 ({type(e).__name__}): {e!r}")
        return []

    video_id = video_meta.get("video_id", "")
    channel  = video_meta.get("channel", "알 수 없음")

    # Step 1 결과 — 영상 전체 논지
    video_summary = str(data.get("video_summary", "") or "")
    main_argument = str(data.get("main_argument", "") or "")
    if main_argument:
        logger.info(f"[YT] 영상 논지: {main_argument}")
    if video_summary:
        logger.info(f"[YT] 요약: {video_summary[:100]}")

    # 발언자 처리 — 빈 값이면 '발언자 미확인'
    speaker_raw = str(data.get("speaker", "") or "").strip()
    if not speaker_raw or speaker_raw in ("알 수 없음", "Unknown", "unknown"):
        speaker_raw = "발언자 미확인"

    raw_quotes = data.get("quotes", []) or []
    logger.info(
        f"[YT] Gemini 반환 quotes={len(raw_quotes)}개 "
        f"(score: {[int(q.get('importance_score', 0) or 0) for q in raw_quotes]}, "
        f"risky: {[bool(q.get('is_risky')) for q in raw_quotes]})"
    )
    for q in raw_quotes:
        if q.get("is_risky"):
            logger.info(
                f"[YT] is_risky=true drop: \"{(q.get('text') or '')[:60]}\""
            )

    quotes: list[YoutubeQuote] = []
    drop_risky = drop_score = drop_riskkw = 0
    for q in raw_quotes:
        if q.get("is_risky"):
            drop_risky += 1
            continue
        if int(q.get("importance_score", 0) or 0) < 55:
            drop_score += 1
            continue
        if RISK_KW.search(q.get("text", "") or ""):
            drop_riskkw += 1
            continue
        ts = int(q.get("timestamp_sec", 0) or 0)
        ctx_before = str(q.get("context_before", "") or "")
        # 영상 전체 논지를 앞 맥락에 주입 — DraftWriter 가 서사 뼈대로 활용
        if main_argument:
            ctx_before = f"[영상 핵심 논지] {main_argument}\n\n{ctx_before}".strip()
        quotes.append(YoutubeQuote(
            text=str(q.get("text", "") or ""),
            speaker=speaker_raw,
            channel=channel,
            video_id=video_id,
            video_title=str(data.get("video_title", "") or ""),
            timestamp=str(q.get("timestamp", "00:00") or "00:00"),
            timestamp_sec=ts,
            topic_tag=str(q.get("topic_tag", "macro") or "macro"),
            importance_score=int(q.get("importance_score", 60) or 60),
            context_before=ctx_before,
            context_after=str(q.get("context_after", "") or ""),
            url=f"https://youtu.be/{video_id}?t={ts}",
            is_risky=False,
        ))

    quotes = _dedup_quotes(quotes)
    logger.info(
        f"[YT] 발언 추출 완료: {len(quotes)}개 "
        f"(drop risky={drop_risky}, score<55={drop_score}, riskkw={drop_riskkw})"
    )
    return quotes


def _dedup_quotes(quotes: list[YoutubeQuote]) -> list[YoutubeQuote]:
    """같은 영상 내 30초 이내 인접 발언 dedup. 영상당 최대 5개."""
    if not quotes:
        return []
    quotes.sort(key=lambda q: q.timestamp_sec)
    kept = [quotes[0]]
    for q in quotes[1:]:
        if q.timestamp_sec - kept[-1].timestamp_sec > 30:
            kept.append(q)
    return kept[:5]


# ─── DB 저장 ──────────────────────────────────────────────────────────
def save_quotes_to_db(
    quotes: list[YoutubeQuote],
    db_path: str | None = None,
) -> int:
    """quote_hash 기준 UNIQUE 저장. 이미 있으면 skip."""
    path = db_path or _sqlite_path()
    saved = 0
    try:
        conn = sqlite3.connect(path)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS yt_quotes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                quote_hash TEXT UNIQUE,
                text TEXT NOT NULL,
                speaker TEXT,
                channel TEXT,
                video_id TEXT,
                video_title TEXT,
                timestamp TEXT,
                timestamp_sec INTEGER,
                topic_tag TEXT,
                importance_score INTEGER,
                context_before TEXT,
                context_after TEXT,
                url TEXT,
                used INTEGER DEFAULT 0,
                extracted_at REAL
            )
        """)
        for q in quotes:
            qhash = hashlib.md5(
                f"{q.video_id}_{q.timestamp_sec}".encode()
            ).hexdigest()[:16]
            try:
                cursor.execute("""
                    INSERT OR IGNORE INTO yt_quotes
                    (quote_hash, text, speaker, channel, video_id,
                     video_title, timestamp, timestamp_sec, topic_tag,
                     importance_score, context_before, context_after,
                     url, extracted_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    qhash, q.text, q.speaker, q.channel, q.video_id,
                    q.video_title, q.timestamp, q.timestamp_sec, q.topic_tag,
                    q.importance_score, q.context_before, q.context_after,
                    q.url, q.extracted_at,
                ))
                if cursor.rowcount > 0:
                    saved += 1
            except Exception as e:
                logger.debug(f"[YT DB] insert skip: {e}")
        conn.commit()
        conn.close()
        logger.info(f"[YT DB] 신규 저장 {saved}건")
        return saved
    except Exception as e:
        logger.warning(f"[YT DB] 저장 실패: {e}")
        return 0


def get_quote_by_key(
    video_id: str,
    timestamp_sec: int,
    db_path: str | None = None,
) -> YoutubeQuote | None:
    """video_id+timestamp_sec 로 YoutubeQuote 복원 (콜백 핸들러용)."""
    path = db_path or _sqlite_path()
    try:
        conn = sqlite3.connect(path)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT text, speaker, channel, video_title, timestamp,
                   topic_tag, importance_score, context_before,
                   context_after, url
            FROM yt_quotes
            WHERE video_id = ? AND timestamp_sec = ?
            LIMIT 1
        """, (video_id, timestamp_sec))
        row = cursor.fetchone()
        conn.close()
        if not row:
            return None
        return YoutubeQuote(
            text=row[0], speaker=row[1], channel=row[2],
            video_id=video_id, video_title=row[3],
            timestamp=row[4], timestamp_sec=timestamp_sec,
            topic_tag=row[5], importance_score=row[6],
            context_before=row[7], context_after=row[8],
            url=row[9], is_risky=False,
        )
    except Exception as e:
        logger.warning(f"[YT DB] get_quote 실패: {e}")
        return None


def mark_used(
    video_id: str,
    timestamp_sec: int,
    db_path: str | None = None,
) -> None:
    path = db_path or _sqlite_path()
    try:
        conn = sqlite3.connect(path)
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE yt_quotes SET used = 1
            WHERE video_id = ? AND timestamp_sec = ?
        """, (video_id, timestamp_sec))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning(f"[YT DB] mark_used 실패: {e}")


# ─── 메인 처리 ────────────────────────────────────────────────────────
async def process_youtube_url(
    url: str,
    channel_name: str = "",
) -> list[YoutubeQuote]:
    """유튜브 URL → 발언 리스트. 텔레그램 봇 핸들러에서 호출."""
    video_id = extract_video_id(url)
    if not video_id:
        logger.warning(f"[YT] 유효하지 않은 URL: {url}")
        return []
    video_meta = {
        "video_id": video_id,
        "channel":  channel_name or "알 수 없음",
        "title":    "",
        "url":      url,
    }
    snippets = await fetch_transcript(video_id)
    if not snippets:
        logger.warning(f"[YT] 자막 추출 실패: {video_id}")
        return []
    total = len(snippets)
    snippets = _filter_intro(snippets)
    logger.info(
        f"[YT] 인트로(3분 이내) 제외: {total - len(snippets)}건 drop, "
        f"{len(snippets)}건 유지"
    )
    if not snippets:
        logger.warning(f"[YT] 인트로 제외 후 남은 자막 없음: {video_id}")
        return []
    quotes = await extract_quotes(snippets, video_meta)
    if quotes:
        save_quotes_to_db(quotes)
    return quotes
