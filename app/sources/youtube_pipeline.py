"""YouTube URL → Gemini 직접 영상 분석 → OpenAI 초안 생성.

Gemini file_data 로 URL 전달 시:
  - YouTube 자막/영상 전체 처리 (4,000자 제한 없음)
  - 클라우드 IP 차단 문제 없음 (Gemini 가 직접 분석)
  - 자막 추출 코드 불필요

역할 분담 (body 구조 + 자연 truncation):
  OpenAI DraftWriter : full_analysis 전체 + STORYTELLING 지시
  Gemini researcher  : body 앞부분 = 핵심 주장 + 발언
  Perplexity / Grok  : body[:1000] ≈ downstream_summary 만
  Haiku Reviewer     : 초안만 수신
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
    """프로젝트 표준 DB 경로 (settings.database_url)."""
    url = settings.database_url or ""
    m = re.match(r"sqlite:///(.+)", url)
    return m.group(1) if m else "./x_poster.db"


# ─── URL 파싱 ─────────────────────────────────────────────────────────
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


def normalize_url(url: str) -> str:
    video_id = extract_video_id(url)
    if not video_id:
        return url
    return f"https://www.youtube.com/watch?v={video_id}"


# ─── 데이터 클래스 ────────────────────────────────────────────────────
@dataclass
class YoutubeAnalysis:
    """Gemini 영상 분석 결과 — 단일 모델."""
    video_id:           str
    url:                str
    channel:            str
    speaker:            str
    video_summary:      str
    main_argument:      str
    full_analysis:      str        # OpenAI 투입용 전체 분석
    downstream_summary: str        # Perplexity/Grok 용 요약
    duration_min:       int = 0
    analyzed_at:        float = field(default_factory=time.time)

    def to_pipeline_input(self) -> dict:
        """뉴스 파이프라인 SourceItemCreate 형식.

        source_text body 구조 (자연 truncation 으로 역할 분담):
          ① [STORYTELLING 지시]      — OpenAI 가 맨 위에서 system 처럼 읽음
          ② [핵심 주장]              — 짧은 요약 (Perplexity/Grok 자연 도달)
          ③ [영상 분석 상세]         — full_analysis 원문 (OpenAI 전체 읽음)
        """
        storytelling_header = (
            "[유튜브 영상 분석 모드 — 스토리텔링 구조 필수]\n"
            "아래 영상 분석 결과를 바탕으로 포스트를 작성합니다.\n"
            "\n"
            "포스트 구조 (반드시 준수):\n"
            "① 배경: 독자가 이미 아는 현실 1~2줄\n"
            "② 긴장: 발언자가 지적한 이상한 점 1~2줄\n"
            "③ 반전: 아무도 말 안 하는 모순 1~2줄\n"
            "④ 내 해석: 해석 동사 1회 + '나는' 1회\n"
            "⑤ 스테이크: 독자 지갑·포지션 연결\n"
            "⑥ 예측: 시간+레벨+반증조건\n"
            "\n"
            "추가 규칙:\n"
            "- 발언자 주장은 큰따옴표로 인용\n"
            "- 출처(채널명·타임스탬프) 포스트 끝에 명시\n"
            "- 분석 결과에 없는 사실 추가 금지\n"
        )
        body = (
            f"{storytelling_header}\n"
            f"[핵심 주장]\n{self.main_argument}\n\n"
            f"[요약]\n{self.downstream_summary or self.video_summary}\n\n"
            f"{self.full_analysis}"
        )
        title_hint = (self.main_argument or self.video_summary or "영상 분석")[:50]
        return {
            "title": (
                f"[유튜브] {self.speaker or self.channel}: {title_hint}"
            ),
            "body": body,
            "url": self.url,
            "source": "youtube",
            "source_type": "youtube",
            "channel": self.channel,
            "speaker": self.speaker,
            "summary": self.downstream_summary,
            "main_argument": self.main_argument,
        }


# ─── Gemini 분석 프롬프트 ────────────────────────────────────────────
GEMINI_VIDEO_ANALYSIS_PROMPT = """당신은 한국 매크로·크립토·경제 전문 콘텐츠 편집자입니다.
이 유튜브 영상을 처음부터 끝까지 전부 분석하세요.

## 분석 순서

### Step 1: 영상 전체 파악
- 발언자가 이 영상에서 말하려는 핵심 주제
- 영상 흐름 (도입 → 전개 → 결론)
- 발언자 이름 (자막·화면에서 파악, 모르면 "발언자 미확인")

### Step 2: 핵심 발언 추출
영상 전체에서 포스트 소재가 될 발언 3~5개.
각 발언:
- 타임스탬프 명시 (MM:SS)
- 앞뒤 맥락 3~5문장 포함
- 단정형·예측형·대립형 발언 우선
- 인트로·아웃트로·광고 제외

### Step 3: 스토리텔링 뼈대
① 배경: 독자가 이미 아는 현실 1~2줄
② 긴장: 발언자가 지적한 이상한 점
③ 반전: 아무도 말 안 하는 모순
④ 결론: 발언자 핵심 주장 1문장

## JSON만 반환 (다른 텍스트 절대 금지)
{
  "speaker": "발언자 이름 또는 발언자 미확인",
  "channel": "채널명",
  "duration_min": 숫자,
  "main_argument": "발언자 핵심 주장 1문장 한국어",
  "video_summary": "영상 전체 핵심 논지 2~3문장 한국어",
  "story_structure": {
    "background": "배경 1~2줄",
    "tension": "긴장 1~2줄",
    "reversal": "반전 1~2줄",
    "conclusion": "결론 1줄"
  },
  "key_quotes": [
    {
      "text": "발언 원문 80자 이내",
      "timestamp": "MM:SS",
      "context_before": "앞 맥락 3~5문장",
      "context_after": "뒤 맥락 3~5문장",
      "topic_tag": "macro|crypto|policy|semi|geo|real_estate|equity",
      "importance": 0-100
    }
  ],
  "downstream_summary": "핵심 주장 요약 300자 이내"
}"""


# ─── Gemini 직접 분석 ────────────────────────────────────────────────
_GEMINI_MODEL = "gemini-2.5-flash-preview-05-20"


async def analyze_video_with_gemini(
    url: str,
    channel_name: str = "",
) -> YoutubeAnalysis | None:
    api_key = settings.gemini_api_key
    if not api_key:
        logger.error("[YT] Gemini API 키 없음")
        return None

    video_id = extract_video_id(url)
    if not video_id:
        logger.warning(f"[YT] 유효하지 않은 URL: {url}")
        return None

    normalized = normalize_url(url)
    logger.info(f"[YT] Gemini 분석 시작: {video_id}")

    payload = {
        "contents": [{
            "parts": [
                {
                    "file_data": {
                        "mime_type": "video/mp4",
                        "file_uri": normalized,
                    },
                },
                {"text": GEMINI_VIDEO_ANALYSIS_PROMPT},
            ],
        }],
        "generationConfig": {
            "temperature": 0.0,
            "maxOutputTokens": 4000,
            "responseMimeType": "application/json",
        },
    }
    api_url = (
        "https://generativelanguage.googleapis.com/v1beta/"
        f"models/{_GEMINI_MODEL}:generateContent?key={api_key}"
    )

    last_err: Exception | None = None
    for attempt in range(3):
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post(api_url, json=payload)
                if resp.status_code in (429, 500, 502, 503, 504):
                    wait = 2 ** attempt
                    logger.info(
                        f"[YT] Gemini {resp.status_code} retry "
                        f"{attempt + 1}/3 after {wait}s"
                    )
                    await asyncio.sleep(wait)
                    continue
                if resp.status_code != 200:
                    logger.warning(
                        f"[YT] Gemini HTTP {resp.status_code}: "
                        f"{resp.text[:500]}"
                    )
                    return None
                body = resp.json()
            try:
                text = body["candidates"][0]["content"]["parts"][0]["text"]
            except (KeyError, IndexError, TypeError) as ke:
                logger.warning(
                    f"[YT] Gemini 응답 구조 이상 ({type(ke).__name__}): "
                    f"{json.dumps(body)[:500]}"
                )
                return None
            text = text.strip().strip("```json").strip("```").strip()
            try:
                data = json.loads(text)
            except json.JSONDecodeError as je:
                logger.warning(
                    f"[YT] JSON 파싱 실패 ({je}) — 원문 앞 500자: {text[:500]!r}"
                )
                if attempt < 2:
                    await asyncio.sleep(2)
                    continue
                return None

            story = data.get("story_structure", {}) or {}
            quotes_text_parts = []
            for q in (data.get("key_quotes", []) or []):
                quotes_text_parts.append(
                    f"[{q.get('timestamp', '??:??')}] "
                    f"\"{q.get('text', '')}\"\n"
                    f"앞 맥락: {q.get('context_before', '')}\n"
                    f"뒤 맥락: {q.get('context_after', '')}"
                )
            quotes_text = "\n\n".join(quotes_text_parts)

            full_analysis = (
                f"[영상 분석]\n"
                f"발언자: {data.get('speaker', '발언자 미확인')}\n"
                f"채널: {data.get('channel', channel_name or '알 수 없음')}\n"
                f"핵심 주장: {data.get('main_argument', '')}\n\n"
                f"[스토리 구조]\n"
                f"배경: {story.get('background', '')}\n"
                f"긴장: {story.get('tension', '')}\n"
                f"반전: {story.get('reversal', '')}\n"
                f"결론: {story.get('conclusion', '')}\n\n"
                f"[주요 발언]\n{quotes_text}\n\n"
                f"[출처]\n{normalized}"
            )

            analysis = YoutubeAnalysis(
                video_id=video_id,
                url=normalized,
                channel=str(
                    data.get("channel", channel_name or "알 수 없음")
                    or (channel_name or "알 수 없음")
                ),
                speaker=str(data.get("speaker", "발언자 미확인") or "발언자 미확인"),
                video_summary=str(data.get("video_summary", "") or ""),
                main_argument=str(data.get("main_argument", "") or ""),
                full_analysis=full_analysis,
                downstream_summary=str(
                    data.get("downstream_summary", "") or ""
                ),
                duration_min=int(data.get("duration_min", 0) or 0),
            )
            logger.info(
                f"[YT] 분석 완료: {video_id} "
                f"speaker={analysis.speaker} "
                f"quotes={len(data.get('key_quotes', []) or [])}개"
            )
            return analysis

        except Exception as e:
            last_err = e
            logger.warning(
                f"[YT] 분석 실패 (attempt {attempt + 1}/3) "
                f"({type(e).__name__}): {e!r}"
            )
            if attempt < 2:
                await asyncio.sleep(2 ** attempt)
                continue
    if last_err:
        logger.warning(f"[YT] 최종 실패: {last_err!r}")
    return None


# ─── DB 저장 / 조회 ──────────────────────────────────────────────────
def _ensure_table(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS yt_analyses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            video_id TEXT UNIQUE,
            url TEXT,
            channel TEXT,
            speaker TEXT,
            video_summary TEXT,
            main_argument TEXT,
            full_analysis TEXT,
            downstream_summary TEXT,
            duration_min INTEGER,
            analyzed_at REAL,
            used INTEGER DEFAULT 0
        )
    """)


def save_analysis_to_db(
    analysis: YoutubeAnalysis,
    db_path: str | None = None,
) -> None:
    path = db_path or _sqlite_path()
    try:
        conn = sqlite3.connect(path)
        _ensure_table(conn)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO yt_analyses
            (video_id, url, channel, speaker,
             video_summary, main_argument,
             full_analysis, downstream_summary,
             duration_min, analyzed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            analysis.video_id, analysis.url,
            analysis.channel, analysis.speaker,
            analysis.video_summary, analysis.main_argument,
            analysis.full_analysis, analysis.downstream_summary,
            analysis.duration_min, analysis.analyzed_at,
        ))
        conn.commit()
        conn.close()
        logger.info(f"[YT DB] 저장: {analysis.video_id}")
    except Exception as e:
        logger.warning(f"[YT DB] 저장 실패: {e}")


def get_analysis_from_db(
    video_id: str,
    db_path: str | None = None,
) -> YoutubeAnalysis | None:
    """7일 캐시."""
    path = db_path or _sqlite_path()
    try:
        conn = sqlite3.connect(path)
        _ensure_table(conn)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT video_id, url, channel, speaker,
                   video_summary, main_argument,
                   full_analysis, downstream_summary,
                   duration_min, analyzed_at
            FROM yt_analyses
            WHERE video_id = ? AND analyzed_at > ?
            LIMIT 1
        """, (video_id, time.time() - 86400 * 7))
        row = cursor.fetchone()
        conn.close()
        if not row:
            return None
        return YoutubeAnalysis(
            video_id=row[0] or "",
            url=row[1] or "",
            channel=row[2] or "",
            speaker=row[3] or "",
            video_summary=row[4] or "",
            main_argument=row[5] or "",
            full_analysis=row[6] or "",
            downstream_summary=row[7] or "",
            duration_min=int(row[8] or 0),
            analyzed_at=float(row[9] or time.time()),
        )
    except Exception as e:
        logger.warning(f"[YT DB] 조회 실패: {e}")
        return None


def mark_analysis_used(
    video_id: str, db_path: str | None = None,
) -> None:
    path = db_path or _sqlite_path()
    try:
        conn = sqlite3.connect(path)
        _ensure_table(conn)
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE yt_analyses SET used = 1 WHERE video_id = ?",
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
) -> YoutubeAnalysis | None:
    """유튜브 URL → Gemini 직접 분석 → YoutubeAnalysis. 7일 캐시."""
    video_id = extract_video_id(url)
    if not video_id:
        logger.warning(f"[YT] 유효하지 않은 URL: {url}")
        return None

    cached = get_analysis_from_db(video_id)
    if cached:
        logger.info(f"[YT] 캐시 반환: {video_id} (analyzed {int(time.time() - cached.analyzed_at)}s 전)")
        return cached

    analysis = await analyze_video_with_gemini(url, channel_name)
    if not analysis:
        return None
    save_analysis_to_db(analysis)
    return analysis
