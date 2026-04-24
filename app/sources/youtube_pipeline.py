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
        """기존 뉴스 파이프라인 SourceItemCreate 형식으로 변환.

        뉴스 기사와 동일하게 처리되도록 body 를 순수 자막 + 최소 메타로 구성.
        스토리텔링 / 요약 주입 없음 — 파이프라인이 스스로 분석.
        """
        # 제목용 힌트: 자막 맨 앞 문장 하나 (너무 길면 잘라냄)
        first_sentence = ""
        for line in (self.full_text or "").splitlines():
            stripped = re.sub(r"^\[\d+:\d+\]\s*", "", line.strip())
            if stripped:
                first_sentence = stripped[:60]
                break

        body = (
            f"채널: {self.channel}\n"
            f"영상 URL: {self.url}\n"
            f"길이: {self.duration_min}분\n\n"
            f"{self.full_text}"
        )
        return {
            "title": (
                f"[유튜브] {self.speaker or self.channel}"
                + (f": {first_sentence}" if first_sentence else "")
            ),
            "body": body,
            "url": self.url,
            "source": "youtube",
            "source_type": "youtube",
            "channel": self.channel,
            "speaker": self.speaker,
            "summary": self.summary,  # 카드 미리보기용, 파이프라인엔 주입 안 됨
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
async def fetch_full_transcript(video_id: str) -> tuple[list[dict], int]:
    """1차 youtube-transcript-api → 실패 시 2차 Gemini fallback.

    반환: (snippets, duration_sec).
      - duration_sec = 0 이면 추정 불가 (호출자가 fallback 로직으로 추정).
      - youtube-transcript-api 는 duration 미제공 → 마지막 snippet 기준 추정.
      - Gemini fallback 은 영상 메타의 실제 duration_sec 반환.
    """
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
        # duration_sec 추정: 마지막 snippet.start + duration
        if snippets:
            last = max(snippets, key=lambda s: s.get("start", 0) or 0)
            estimated = int(
                (last.get("start", 0) or 0) + (last.get("duration", 30) or 30)
            )
        else:
            estimated = 0
        return snippets, estimated
    except Exception as e:
        logger.warning(f"[YT] youtube-transcript-api 실패: {e}")

    result = await _gemini_transcript_fallback(video_id)
    if isinstance(result, dict):
        return result.get("snippets", []), int(result.get("duration_sec", 0) or 0)
    # 구버전 호환 (리스트 반환 경로) — 사실상 미도달
    return (result or []), 0


async def _gemini_transcript_fallback(video_id: str) -> dict:
    """Gemini 2.5 Flash file_data fallback — 영상 전체 균등 커버 요구.

    반환: {"snippets": [...], "duration_sec": int}. 실패 시 {"snippets": [], "duration_sec": 0}.
    """
    empty = {"snippets": [], "duration_sec": 0}
    api_key = settings.gemini_api_key
    if not api_key:
        return empty
    url = f"https://www.youtube.com/watch?v={video_id}"
    prompt = (
        "이 유튜브 영상의 자막을 추출하세요. "
        "**영상을 끝까지 전부 분석**하고 전체 길이(초)를 정확히 측정해야 합니다.\n"
        "\n"
        "절대 규칙 (위반 시 응답 reject):\n"
        "1. duration_sec 필드는 반드시 영상의 **실제 총 길이(초)** 로 채움.\n"
        "   0 또는 추정 없이 응답 불가.\n"
        "2. snippets 는 **영상을 5 구간으로 균등 분할**하여 각 구간마다\n"
        "   최소 6개 이상 (총 30개 이상) 포함. 영상 끝부분(마지막 20%) 반드시 포함.\n"
        "3. 가장 마지막 snippet 의 start 값은 duration_sec 의 80% 이상이어야 함.\n"
        "4. 각 snippet 은 완전한 문장 1~3개 (50자 이상).\n"
        "5. 영상이 1분 미만인 경우에만 snippets 개수 완화 가능.\n"
        "\n"
        "JSON 만 반환 (다른 텍스트 금지):\n"
        "{\n"
        '  "duration_sec": 1020,\n'
        '  "snippets": [\n'
        '    {"start": 15,   "text": "..."},\n'
        '    {"start": 230,  "text": "..."},\n'
        '    {"start": 500,  "text": "..."},\n'
        '    {"start": 780,  "text": "..."},\n'
        '    {"start": 1000, "text": "..."}\n'
        "  ]\n"
        "}"
    )
    # responseSchema 로 Gemini 출력 강제 — duration_sec required, snippets minItems=15
    response_schema = {
        "type": "object",
        "properties": {
            "duration_sec": {"type": "integer", "minimum": 1},
            "snippets": {
                "type": "array",
                "minItems": 15,
                "items": {
                    "type": "object",
                    "properties": {
                        "start": {"type": "integer", "minimum": 0},
                        "text":  {"type": "string",  "minLength": 10},
                    },
                    "required": ["start", "text"],
                },
            },
        },
        "required": ["duration_sec", "snippets"],
    }
    payload = {
        "contents": [{
            "parts": [
                {"text": prompt},
                {"file_data": {"mime_type": "video/youtube", "file_uri": url}},
            ],
        }],
        "generationConfig": {
            "temperature": 0.0,
            "maxOutputTokens": 15000,
            "responseMimeType": "application/json",
            "responseSchema": response_schema,
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
                return empty
            body = resp.json()
            try:
                text = body["candidates"][0]["content"]["parts"][0]["text"]
            except (KeyError, IndexError, TypeError) as ke:
                logger.warning(
                    f"[YT] Gemini fallback 응답 구조 이상 ({type(ke).__name__}): "
                    f"{json.dumps(body)[:500]}"
                )
                return empty
            text = text.strip().strip("```json").strip("```").strip()

            # 신 스키마: {duration_sec, snippets}. 구 스키마: [...] 배열.
            parsed = _loose_json_object(text)
            if parsed is not None and isinstance(parsed, dict):
                duration_sec = int(parsed.get("duration_sec", 0) or 0)
                snippets_raw = parsed.get("snippets", []) or []
            else:
                arr = _loose_json_array(text)
                if arr is None:
                    logger.warning(
                        f"[YT] Gemini fallback JSON 파싱 실패 — 원문 앞 500자: "
                        f"{text[:500]!r}"
                    )
                    return empty
                duration_sec = 0
                snippets_raw = arr

            if len(snippets_raw) < 20:
                logger.warning(
                    f"[YT] Gemini fallback {len(snippets_raw)}개 (권장 30+)"
                )
            # duration_sec 보정 — Gemini 가 0 반환해도 snippet 의 max start 로 추정
            if duration_sec <= 0 and snippets_raw:
                try:
                    max_start = max(
                        int(s.get("start", 0) or 0) for s in snippets_raw
                    )
                    # 마지막 발언 이후 평균 3초 마진 + 대략 10% 여유
                    duration_sec = int(max_start * 1.1) + 3
                    logger.warning(
                        f"[YT] duration_sec 누락 — max_start 기준 추정: {duration_sec}초"
                    )
                except Exception:
                    pass
            logger.info(
                f"[YT] Gemini fallback 성공: {len(snippets_raw)}개 "
                f"duration={duration_sec}초"
            )
            return {
                "snippets": [
                    {
                        "start":    float(d.get("start", 0) or 0),
                        "duration": 3.0,
                        "text":     str(d.get("text", "") or ""),
                    }
                    for d in snippets_raw
                ],
                "duration_sec": duration_sec,
            }
    except Exception as e:
        logger.warning(
            f"[YT] Gemini fallback 실패 ({type(e).__name__}): {e!r}"
        )
        return empty


# ─── (제거) Gemini 요약 호출 — 자막만 파이프라인 투입 정책으로 전환 ─
# 카드 미리보기용 summary 는 _build_preview_summary 로 full_text 에서 발췌.


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

    snippets, duration_sec = await fetch_full_transcript(video_id)
    if not snippets:
        logger.warning(f"[YT] 자막 추출 실패: {video_id}")
        return None

    filtered = _filter_intro_adaptive(snippets)
    if not filtered:
        logger.warning(f"[YT] 자막 필터링 후 남은 게 없음: {video_id}")
        return None

    full_text = _snippets_to_text(filtered)

    # duration_min — Gemini 가 반환한 실제 영상 길이 우선, 없으면 마지막 snippet 기준 추정
    if duration_sec > 0:
        duration_min = int(duration_sec / 60)
    elif snippets:
        last = max(snippets, key=lambda s: s.get("start", 0) or 0)
        estimated_sec = int(
            (last.get("start", 0) or 0) + (last.get("duration", 30) or 30)
        )
        duration_min = int(estimated_sec / 60)
    else:
        duration_min = 0

    # 카드 미리보기용 summary — full_text 앞 부분에서 발췌 (추가 AI 호출 없음)
    summary = _build_preview_summary(full_text, max_chars=400)

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
        f"({duration_min}분 / {len(full_text)}자)"
    )
    return transcript


def _build_preview_summary(full_text: str, max_chars: int = 400) -> str:
    """full_text 에서 카드 미리보기용 발췌. 타임스탬프 prefix 제거 후 앞부분만."""
    if not full_text:
        return ""
    lines = []
    for line in full_text.splitlines():
        stripped = re.sub(r"^\[\d+:\d+\]\s*", "", line.strip())
        if stripped:
            lines.append(stripped)
    joined = " ".join(lines)
    return joined[:max_chars].rstrip() + ("…" if len(joined) > max_chars else "")
