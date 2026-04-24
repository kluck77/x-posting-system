"""유튜브 전체 자막 → 5-AI 파이프라인 투입 (v2 full-transcript).

역할 분담 (source_text 구조 + 자연 truncation 으로 달성):
  OpenAI  : source_text 전체 = [핵심 논지] + [전체 자막]  → 모든 정보 수신
  Gemini  : source_text 앞부분 = [핵심 논지] + 자막 시작부 → 논지 중심
  Perplexity / Grok : source_text[:1000] ≈ [핵심 논지]     → 요약만 검증
  Haiku   : 초안만 수신 (Review 단계)                     → 자막 미수신

전처리:
  1차 youtube-transcript-api
  2차 Gemini 2.5 Flash file_data fallback (영상 전체 골고루 분포 요구)
"""
from __future__ import annotations

import asyncio
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


# ─── JSON 복구 파서 ───────────────────────────────────────────────────
def _loose_json_array(raw: str) -> list | None:
    if not raw:
        return None
    try:
        val = json.loads(raw)
        return val if isinstance(val, list) else None
    except Exception:
        pass
    i = raw.find("[")
    if i < 0:
        return None
    for j in range(len(raw) - 1, i, -1):
        if raw[j] == "]":
            try:
                val = json.loads(raw[i : j + 1])
                if isinstance(val, list):
                    return val
            except Exception:
                continue
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


# ─── Gemini 호출 helper ──────────────────────────────────────────────
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


# ─── 리스크 키워드 (본문 안전장치) ───────────────────────────────────
RISK_KW = re.compile(r"욕설|명예훼손|허위|개인정보|사생활")


# ─── 데이터 모델 ─────────────────────────────────────────────────────
@dataclass
class YoutubeTranscript:
    """전체 자막 + 메타데이터 + 핵심 논지 요약."""
    video_id:       str
    url:            str
    channel:        str
    full_text:      str            # 타임스탬프 포함 전체 자막
    summary:        str = ""       # Gemini 요약 (Perplexity/Grok 용)
    speaker:        str = ""
    duration_min:   int = 0
    extracted_at:   float = field(default_factory=time.time)

    def to_pipeline_input(self) -> dict:
        """기존 파이프라인 SourceItemCreate 형식으로 변환.

        source_text 구조:
          ① [유튜브 영상 분석] 헤더
          ② [핵심 논지] summary — 자연 truncation 으로 Perplexity/Grok 에 도달
          ③ [전체 자막] full_text — OpenAI DraftWriter 가 전부 읽음
          ④ [지시사항] 인용/맥락/출처 규칙
        """
        body = (
            f"[유튜브 영상 분석]\n"
            f"채널: {self.channel}\n"
            f"영상 URL: {self.url}\n"
            f"길이: {self.duration_min}분\n\n"
            f"[핵심 논지]\n{self.summary or '(요약 없음)'}\n\n"
            f"[전체 자막]\n{self.full_text}\n\n"
            f"[지시사항]\n"
            f"- 영상 발언을 큰따옴표로 인용하고 타임스탬프 명시\n"
            f"- 대립각 / 스테이크 / 예측 3종 세트 / 리플 유도 규칙 적용\n"
            f"- 임의 사실 추가 금지 — 자막에 있는 내용만 활용\n"
            f"- 출처: 채널명·영상 URL 포스트 끝에 명시"
        )
        title_hint = (self.summary or "전체 자막 분석")[:50]
        return {
            "title": f"[유튜브] {self.speaker or self.channel}: {title_hint}",
            "body": body,
            "url": self.url,
            "source": "youtube",
            "source_type": "youtube",
            "channel": self.channel,
            "speaker": self.speaker,
            "summary": self.summary,
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


# ─── 자막 정제 ───────────────────────────────────────────────────────
def _snippets_to_text(snippets: list[dict]) -> str:
    """스니펫 → 타임스탬프 포함 전체 텍스트."""
    lines = []
    for s in snippets:
        sec = int(s.get("start", 0) or 0)
        mm, ss = sec // 60, sec % 60
        lines.append(f"[{mm:02d}:{ss:02d}] {(s.get('text') or '').strip()}")
    return "\n".join(lines)


def _filter_intro_adaptive(
    snippets: list[dict],
    intro_sec: int = 180,
    keep_min_ratio: float = 0.3,
) -> list[dict]:
    """적응형 인트로 필터.

    필터 후 전체의 keep_min_ratio 미만만 남으면 원본 유지
    (짧은 영상 / 앞부분 편중된 Gemini fallback 대응).
    """
    if not snippets:
        return snippets
    filtered = [s for s in snippets if float(s.get("start", 0) or 0) >= intro_sec]
    if len(filtered) < len(snippets) * keep_min_ratio:
        logger.info(
            f"[YT] 인트로 필터 해제 — 필터 후 {len(filtered)}/{len(snippets)} "
            f"({keep_min_ratio * 100:.0f}% 미만) → 원본 유지"
        )
        return snippets
    logger.info(
        f"[YT] 인트로 필터 적용 — {len(snippets) - len(filtered)}건 drop, "
        f"{len(filtered)}건 유지"
    )
    return filtered


# ─── 자막 추출 ───────────────────────────────────────────────────────
async def fetch_full_transcript(video_id: str) -> list[dict]:
    """1차 youtube-transcript-api → 실패 시 2차 Gemini fallback."""
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
        logger.info(f"[YT] 자막 추출 성공: {len(snippets)}개 스니펫")
        return snippets
    except Exception as e:
        logger.warning(f"[YT] youtube-transcript-api 실패: {e}")

    return await _gemini_transcript_fallback(video_id)


async def _gemini_transcript_fallback(video_id: str) -> list[dict]:
    """Gemini 2.5 Flash file_data fallback — 영상 전체 균등 커버 요구."""
    api_key = settings.gemini_api_key
    if not api_key:
        return []
    url = f"https://www.youtube.com/watch?v={video_id}"
    prompt = (
        "이 유튜브 영상의 자막을 타임스탬프(초) 단위로 추출하세요.\n"
        "\n"
        "필수 준수 사항:\n"
        "1. 영상 전체에 걸쳐 균등하게 분포된 최소 20개 이상의 스니펫 추출\n"
        "2. 앞부분·중간·후반부 골고루 포함 (첫 3분 편중 금지)\n"
        "3. 각 항목의 'start' 는 정수초 (다양한 구간에서)\n"
        "4. 최대 200개까지\n"
        "\n"
        "JSON 배열로만 반환 (설명·코멘트 금지):\n"
        '[{"start": 정수초, "text": "발언 내용"}, ...]'
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
            "maxOutputTokens": 8000,
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
            if len(data) < 20:
                logger.warning(
                    f"[YT] Gemini fallback 스니펫 {len(data)}개 (권장 20+)"
                )
            logger.info(f"[YT] Gemini fallback 성공: {len(data)}개")
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


# ─── Gemini 핵심 논지 요약 (Perplexity/Grok 용) ─────────────────────
SUMMARY_PROMPT_TEMPLATE = """아래는 한국 경제·크립토 유튜브 채널({channel})의 전체 자막입니다.

다음을 한국어로 요약하세요:
1. 발언자의 핵심 주장 1~2개 (대립각이 되는 주장)
2. 주요 논거 3개 (근거·예시·수치)
3. 결론 1문장 (독자에게 무엇을 시사하는가)

500자 이내로 요약. 다른 설명 없이 요약문만 반환."""


async def summarize_for_downstream(
    full_text: str,
    channel: str,
) -> str:
    """전체 자막 → 핵심 논지 요약. Perplexity/Grok 에 전달할 축약본."""
    api_key = settings.gemini_api_key
    if not api_key or not full_text:
        return (full_text or "")[:500]

    prompt = SUMMARY_PROMPT_TEMPLATE.format(channel=channel)
    payload = {
        "contents": [{
            "parts": [
                {"text": f"{prompt}\n\n자막:\n{full_text[:8000]}"}
            ],
        }],
        "generationConfig": {
            "temperature": 0.0,
            "maxOutputTokens": 1500,
        },
    }
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await _gemini_post_with_retry(
                client,
                "https://generativelanguage.googleapis.com/v1beta/"
                f"models/gemini-2.5-flash:generateContent?key={api_key}",
                payload,
            )
            resp.raise_for_status()
            summary = resp.json()[
                "candidates"][0]["content"]["parts"][0]["text"]
            summary = summary.strip()
            logger.info(f"[YT] 핵심 논지 요약 완료: {len(summary)}자")
            return summary
    except Exception as e:
        logger.warning(f"[YT] 요약 실패 ({type(e).__name__}): {e!r}")
        return full_text[:500]


# ─── DB 저장 ─────────────────────────────────────────────────────────
def save_transcript_to_db(
    transcript: YoutubeTranscript,
    db_path: str | None = None,
) -> None:
    path = db_path or _sqlite_path()
    try:
        conn = sqlite3.connect(path)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS yt_transcripts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                video_id TEXT UNIQUE,
                url TEXT,
                channel TEXT,
                speaker TEXT,
                full_text TEXT,
                summary TEXT,
                duration_min INTEGER,
                extracted_at REAL,
                used INTEGER DEFAULT 0
            )
        """)
        cursor.execute("""
            INSERT OR REPLACE INTO yt_transcripts
            (video_id, url, channel, speaker, full_text,
             summary, duration_min, extracted_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            transcript.video_id, transcript.url,
            transcript.channel, transcript.speaker,
            transcript.full_text, transcript.summary,
            transcript.duration_min, transcript.extracted_at,
        ))
        conn.commit()
        conn.close()
        logger.info(f"[YT DB] 저장 완료: {transcript.video_id}")
    except Exception as e:
        logger.warning(f"[YT DB] 저장 실패: {e}")


def get_transcript_by_id(
    video_id: str,
    db_path: str | None = None,
) -> YoutubeTranscript | None:
    """video_id 로 YoutubeTranscript 복원 (텔레그램 콜백용)."""
    path = db_path or _sqlite_path()
    try:
        conn = sqlite3.connect(path)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT url, channel, speaker, full_text,
                   summary, duration_min, extracted_at
            FROM yt_transcripts
            WHERE video_id = ?
            LIMIT 1
        """, (video_id,))
        row = cursor.fetchone()
        conn.close()
        if not row:
            return None
        return YoutubeTranscript(
            video_id=video_id,
            url=row[0] or "",
            channel=row[1] or "",
            speaker=row[2] or "",
            full_text=row[3] or "",
            summary=row[4] or "",
            duration_min=int(row[5] or 0),
            extracted_at=float(row[6] or time.time()),
        )
    except Exception as e:
        logger.warning(f"[YT DB] get_transcript 실패: {e}")
        return None


def mark_transcript_used(
    video_id: str,
    db_path: str | None = None,
) -> None:
    path = db_path or _sqlite_path()
    try:
        conn = sqlite3.connect(path)
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE yt_transcripts SET used = 1 WHERE video_id = ?",
            (video_id,),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning(f"[YT DB] mark_used 실패: {e}")


# ─── 메인 진입점 ─────────────────────────────────────────────────────
async def process_youtube_url(
    url: str,
    channel_name: str = "",
) -> YoutubeTranscript | None:
    """유튜브 URL → YoutubeTranscript 반환. 텔레그램 봇에서 직접 호출."""
    video_id = extract_video_id(url)
    if not video_id:
        logger.warning(f"[YT] 유효하지 않은 URL: {url}")
        return None

    snippets = await fetch_full_transcript(video_id)
    if not snippets:
        logger.warning(f"[YT] 자막 추출 실패: {video_id}")
        return None

    filtered = _filter_intro_adaptive(snippets)
    if not filtered:
        logger.warning(f"[YT] 자막 필터링 후 남은 게 없음: {video_id}")
        return None

    full_text = _snippets_to_text(filtered)
    duration_min = 0
    if snippets:
        last_start = max(float(s.get("start", 0) or 0) for s in snippets)
        duration_min = int(last_start / 60)

    summary = await summarize_for_downstream(
        full_text, channel_name or "알 수 없음"
    )

    transcript = YoutubeTranscript(
        video_id=video_id,
        url=url,
        channel=channel_name or "알 수 없음",
        full_text=full_text,
        summary=summary,
        speaker="",
        duration_min=duration_min,
    )
    save_transcript_to_db(transcript)

    logger.info(
        f"[YT] 처리 완료: {video_id} "
        f"({duration_min}분 / {len(full_text)}자 / summary {len(summary)}자)"
    )
    return transcript
