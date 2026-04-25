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


def _recover_truncated_json(text: str) -> dict | None:
    """토큰 한도 등으로 잘린 Gemini JSON 응답 복구.

    전략 (앞쪽이 valid 한 prefix 라고 가정):
      1) 마지막 valid '}' 위치까지 잘라 재시도 (뒤쪽부터 한 글자씩 줄임)
      2) 닫히지 않은 string + 객체/배열 자동 닫기 시도
    실패 시 None.
    """
    if not text:
        return None
    # 1) 마지막 } 위치들 시도 (뒤에서 앞으로)
    for j in range(len(text) - 1, 0, -1):
        if text[j] == "}":
            try:
                val = json.loads(text[: j + 1])
                if isinstance(val, dict):
                    return val
            except Exception:
                continue
    # 2) 닫히지 않은 구조 추정 닫기
    s = text
    # 짝 안 맞는 따옴표 닫기
    if s.count('"') % 2 == 1:
        s = s + '"'
    # 객체 / 배열 닫기 (단순 균형)
    open_brace  = s.count("{") - s.count("}")
    open_bracket = s.count("[") - s.count("]")
    if open_bracket > 0:
        s = s + ("]" * open_bracket)
    if open_brace > 0:
        s = s + ("}" * open_brace)
    try:
        val = json.loads(s)
        if isinstance(val, dict):
            return val
    except Exception:
        pass
    return None


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


# ─── Gemini 분석 프롬프트 (v3 — 원문 추출 모드, 요약 금지) ───────────
GEMINI_VIDEO_ANALYSIS_PROMPT = """[IDENTITY]
너는 영상 내용을 원문 그대로 추출하는 전사 모듈이다.

[절대 금지]
- 요약 금지
- 압축 금지
- 해석 금지
- 개수 제한 금지
- 버리기 금지
- 재구성 금지
- 한국 현실·맥락 추가 금지
- 영상에 없는 내용 추가 금지

[TASK]
이 영상에서 발언자가 말한 모든 핵심 주장을 추출하라.

핵심 주장이란:
- 발언자가 강조한 것
- 수치가 포함된 것
- 결론으로 제시한 것
- 독자가 행동하도록 유도한 것
- 반복해서 말한 것

추출 방법:
1. 영상 자막 전체를 읽어라
2. 발언자의 말을 원문에 가깝게 추출
3. 개수 제한 없이 전부 가져와라
4. 각 주장에 영상 타임스탬프 포함

[FORMAT JSON 만 반환 — 다른 텍스트 절대 금지]
{
  "speaker": "발언자 이름 또는 발언자 미확인",
  "channel": "채널명",
  "video_title": "영상 제목",
  "duration_min": 0,
  "total_claims": 0,
  "claims": [
    {
      "timestamp": "00:11",
      "claim": "발언자의 핵심 주장 원문",
      "type": "수치|조언|경고|결론|사례",
      "strength": "high|medium|low"
    }
  ],
  "key_numbers": [
    {
      "value": "200달러",
      "context": "월 투자금",
      "timestamp": "01:23"
    }
  ],
  "core_message": "영상 전체의 핵심 메시지 1줄 (요약 아님, 발언자 말 그대로)"
}

[SELF-CHECK]
□ 모든 핵심 주장 추출했는가
□ 개수 제한 없이 전부 가져왔는가
□ 영상에 없는 내용 추가 안 했는가
□ 한국 맥락 추가 안 했는가
□ 원문에 가깝게 추출했는가"""


# ─── Gemini 직접 분석 ────────────────────────────────────────────────
_GEMINI_MODEL = "gemini-2.5-flash"


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
            "maxOutputTokens": 8000,
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
            data = None
            try:
                data = json.loads(text)
            except json.JSONDecodeError as je:
                # 토큰 한도로 잘린 JSON → 부분 복구
                data = _recover_truncated_json(text)
                if isinstance(data, dict):
                    logger.info(
                        f"[YT] JSON 부분 복구 성공 (원본: {je})"
                    )
                else:
                    logger.warning(
                        f"[YT] JSON 파싱 실패 ({je}) — 원문 앞 500자: {text[:500]!r}"
                    )
                    if attempt < 2:
                        await asyncio.sleep(2)
                        continue
                    return None

            # v3 — claims 원문 추출 모드 (개수 제한 없음, 요약 금지)
            claims = data.get("claims", []) or []
            key_numbers = data.get("key_numbers", []) or []
            core_message = str(data.get("core_message", "") or "")

            claim_lines = []
            for c in claims:
                ts = str(c.get("timestamp", "??:??") or "??:??")
                text = str(c.get("claim", "") or "")
                ctype = str(c.get("type", "") or "")
                strength = str(c.get("strength", "") or "")
                if not text:
                    continue
                tag = f"[{ts}]"
                if ctype:
                    tag += f"[{ctype}]"
                if strength:
                    tag += f"[{strength}]"
                claim_lines.append(f"{tag} {text}")
            claims_text = "\n".join(claim_lines)

            num_lines = []
            for n in key_numbers:
                ts = str(n.get("timestamp", "") or "")
                val = str(n.get("value", "") or "")
                ctx = str(n.get("context", "") or "")
                if not val:
                    continue
                num_lines.append(
                    f"- {val}{(' ' + ts) if ts else ''}{(' — ' + ctx) if ctx else ''}"
                )
            numbers_text = "\n".join(num_lines)

            speaker_v = str(data.get("speaker", "발언자 미확인") or "발언자 미확인")
            channel_v = str(data.get("channel", channel_name or "알 수 없음") or (channel_name or "알 수 없음"))
            video_title_v = str(data.get("video_title", "") or "")
            total_claims = int(data.get("total_claims", 0) or len(claims))

            full_analysis = (
                f"[영상 원문 추출]\n"
                f"발언자: {speaker_v}\n"
                f"채널: {channel_v}\n"
                f"제목: {video_title_v}\n"
                f"총 주장 수: {total_claims}\n\n"
                f"[핵심 메시지 (영상 원문)]\n{core_message}\n\n"
                f"[모든 핵심 주장]\n{claims_text}\n\n"
                f"[수치 모음]\n{numbers_text}\n\n"
                f"[출처]\n{normalized}"
            )

            analysis = YoutubeAnalysis(
                video_id=video_id,
                url=normalized,
                channel=channel_v,
                speaker=speaker_v,
                video_summary=core_message,
                main_argument=core_message,
                full_analysis=full_analysis,
                downstream_summary=core_message,
                duration_min=int(data.get("duration_min", 0) or 0),
            )
            logger.info(
                f"[YT] 분석 완료: {video_id} speaker={analysis.speaker} "
                f"claims={total_claims}개 numbers={len(key_numbers)}개"
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
