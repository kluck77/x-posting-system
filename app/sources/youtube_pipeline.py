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


HIGH_VALUE_KW = re.compile(
    r"fed|연준|기준금리|한은|인플레이션|cpi|ppi|고용|실업률"
    r"|비트코인|btc|이더리움|eth|sec|etf|폴리마켓"
    r"|경기침체|recession|달러|원화|환율|금리|채권"
    r"|반도체|엔비디아|삼성|하이닉스|hbm|tsmc"
    r"|부동산|전세|금통위|fomc",
    re.IGNORECASE,
)

RISK_KW = re.compile(r"욕설|명예훼손|허위|개인정보|사생활")


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
        """기존 파이프라인 주입용 dict (SourceItemCreate adapter 에서 소비)."""
        return {
            "title": f"[유튜브 발언] {self.speaker}: {self.text[:60]}",
            "body": (
                f"발언자: {self.speaker}\n"
                f"채널: {self.channel}\n"
                f'발언 원문: "{self.text}"\n\n'
                f"맥락(앞): {self.context_before}\n"
                f"맥락(뒤): {self.context_after}\n\n"
                f"출처: {self.channel} · {self.url}"
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
        "이 유튜브 영상의 주요 발언을 타임스탬프(초)와 함께 추출해 "
        'JSON 배열로만 반환: [{"start": 초, "text": "발언 내용"}, ...]'
    )
    payload = {
        "contents": [{
            "parts": [
                {"text": prompt},
                {"file_data": {"mime_type": "video/youtube", "file_uri": url}},
            ],
        }],
        "generationConfig": {"temperature": 0.0, "maxOutputTokens": 8000},
    }
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                "https://generativelanguage.googleapis.com/v1beta/"
                f"models/gemini-2.5-flash-preview:generateContent?key={api_key}",
                json=payload,
            )
            resp.raise_for_status()
            text = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
            text = text.strip().strip("```json").strip("```").strip()
            data = json.loads(text)
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
        logger.warning(f"[YT] Gemini fallback 실패: {e}")
        return []


# ─── 발언 추출 (Gemini) ───────────────────────────────────────────────
EXTRACTION_PROMPT = """당신은 한국 매크로·크립토 전문 편집자입니다.
아래 유튜브 자막에서 X 포스트 소재가 될 발언을 추출하세요.

선택 기준 (4개 이상 충족):
1. 맥락 없이도 이해 가능
2. 첫 10단어에 훅이 있음
3. 반박 가능한 주장
4. 숫자·비교·예측 포함
5. 단정·비유·격언 포함
6. 7일 이내 시장 사건과 연관

제외: 투자 권유 면책·인사말·추임새

JSON만 반환 (다른 텍스트 금지):
{
  "video_title": "...",
  "speaker": "발언자 이름 또는 채널명",
  "quotes": [
    {
      "text": "발언 원문 (80자 이내)",
      "timestamp_sec": 734,
      "timestamp": "12:14",
      "topic_tag": "macro|crypto|policy|semi|geo|real_estate|equity",
      "importance_score": 0-100,
      "context_before": "앞 맥락 1-2문장",
      "context_after": "뒤 맥락 1-2문장",
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
    """Gemini 로 발언 단위 추출 + 스코어링."""
    if not snippets:
        return []
    api_key = settings.gemini_api_key
    if not api_key:
        return []

    transcript_text = "\n".join(
        f"[{int(s['start']//60):02d}:{int(s['start']%60):02d}] {s['text']}"
        for s in snippets
    )[:4000]

    payload = {
        "systemInstruction": {"parts": [{"text": EXTRACTION_PROMPT}]},
        "contents": [{
            "parts": [{
                "text": (
                    f"채널: {video_meta.get('channel', '알 수 없음')}\n"
                    f"영상: {video_meta.get('title', '')}\n\n"
                    f"자막:\n{transcript_text}"
                ),
            }],
        }],
        "generationConfig": {"temperature": 0.0, "maxOutputTokens": 3000},
    }

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://generativelanguage.googleapis.com/v1beta/"
                f"models/gemini-2.5-flash-preview:generateContent?key={api_key}",
                json=payload,
            )
            resp.raise_for_status()
            raw = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
            raw = raw.strip().strip("```json").strip("```").strip()
            data = json.loads(raw)
    except Exception as e:
        logger.warning(f"[YT] 발언 추출 실패: {e}")
        return []

    video_id = video_meta.get("video_id", "")
    channel  = video_meta.get("channel", "알 수 없음")

    quotes: list[YoutubeQuote] = []
    for q in data.get("quotes", []) or []:
        if q.get("is_risky") or int(q.get("importance_score", 0) or 0) < 55:
            continue
        if RISK_KW.search(q.get("text", "") or ""):
            continue
        ts = int(q.get("timestamp_sec", 0) or 0)
        quotes.append(YoutubeQuote(
            text=str(q.get("text", "") or ""),
            speaker=str(data.get("speaker", channel) or channel),
            channel=channel,
            video_id=video_id,
            video_title=str(data.get("video_title", "") or ""),
            timestamp=str(q.get("timestamp", "00:00") or "00:00"),
            timestamp_sec=ts,
            topic_tag=str(q.get("topic_tag", "macro") or "macro"),
            importance_score=int(q.get("importance_score", 60) or 60),
            context_before=str(q.get("context_before", "") or ""),
            context_after=str(q.get("context_after", "") or ""),
            url=f"https://youtu.be/{video_id}?t={ts}",
            is_risky=False,
        ))

    quotes = _dedup_quotes(quotes)
    logger.info(f"[YT] 발언 추출 완료: {len(quotes)}개")
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
    quotes = await extract_quotes(snippets, video_meta)
    if quotes:
        save_quotes_to_db(quotes)
    return quotes
