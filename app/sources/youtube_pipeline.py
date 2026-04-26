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

    전략:
      1) 자동 closure (string/배열/객체 닫기) 시도
      2) 마지막 valid '}' 위치까지 자르며 재시도
      3) claims/snippets 같은 배열 안의 부분 객체들 살리기 (top-level 키 보존)
    실패 시 None.
    """
    if not text:
        return None

    # 1) 자동 closure 우선 시도 (가장 흔한 케이스)
    closed = _auto_close(text)
    if closed:
        try:
            val = json.loads(closed)
            if isinstance(val, dict):
                return val
        except Exception:
            pass

    # 2) 마지막 } 위치 시도 (sample size 제한 — 너무 큰 텍스트는 sparse 스캔)
    n = len(text)
    step = max(1, n // 5000)
    candidates = list(range(n - 1, 0, -step))
    for j in candidates:
        if text[j] == "}":
            try:
                val = json.loads(text[: j + 1])
                if isinstance(val, dict):
                    return val
            except Exception:
                continue

    # 3) Top-level scalar 키 + 배열 안 partial 복구
    rebuilt = _rebuild_from_partial(text)
    if rebuilt:
        return rebuilt

    return None


def _auto_close(text: str) -> str:
    """잘린 string/배열/객체 closure 시도. 마지막 잘린 부분 정리 후 닫기."""
    s = text.rstrip()
    # 잘린 마지막 부분이 콤마/콜론으로 끝나면 제거
    while s and s[-1] in ",: \t\n":
        s = s[:-1]
    # 짝 안 맞는 따옴표 닫기 (이스케이프 고려)
    quote_count = 0
    i = 0
    while i < len(s):
        if s[i] == "\\" and i + 1 < len(s):
            i += 2
            continue
        if s[i] == '"':
            quote_count += 1
        i += 1
    if quote_count % 2 == 1:
        s = s + '"'
    # 배열/객체 닫기
    open_bracket = s.count("[") - s.count("]")
    open_brace = s.count("{") - s.count("}")
    if open_bracket > 0:
        s = s + ("]" * open_bracket)
    if open_brace > 0:
        s = s + ("}" * open_brace)
    return s


def _rebuild_from_partial(text: str) -> dict | None:
    """top-level scalar 키 + 배열 안 partial 객체들로 dict 재조립.

    예: claims 배열이 70개 객체 중 30개에서 잘렸으면 30개만 살려서 반환.
    """
    out: dict = {}
    # top-level 'key': "value" 또는 'key': number 추출 (배열 시작 전까지)
    head = text.split("[", 1)[0]
    for m in re.finditer(r'"(\w+)"\s*:\s*("([^"]*)"|(-?\d+))', head):
        key = m.group(1)
        if m.group(3) is not None:
            out[key] = m.group(3)
        elif m.group(4) is not None:
            try:
                out[key] = int(m.group(4))
            except Exception:
                pass

    # 배열 안 partial 객체들 ({...} 단위) 복구
    arrays_found: dict[str, list] = {}
    for arr_match in re.finditer(r'"(\w+)"\s*:\s*\[', text):
        key = arr_match.group(1)
        start = arr_match.end()
        items: list = []
        depth = 0
        obj_start = -1
        i = start
        in_str = False
        esc = False
        while i < len(text):
            c = text[i]
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = not in_str
            elif not in_str:
                if c == "{":
                    if depth == 0:
                        obj_start = i
                    depth += 1
                elif c == "}":
                    depth -= 1
                    if depth == 0 and obj_start >= 0:
                        try:
                            items.append(json.loads(text[obj_start : i + 1]))
                        except Exception:
                            pass
                        obj_start = -1
                elif c == "]" and depth == 0:
                    break
            i += 1
        if items:
            arrays_found[key] = items

    out.update(arrays_found)
    return out if out else None


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
    """Gemini 영상 분석 결과 — 단일 모델.

    선택 필드 (atomic_claims, counter_arguments, conclusion_claim, segments,
    examples, preservation_targets) 는 95% 보존형 장문 모드용. 비어 있어도
    기존 동작은 깨지지 않는다 (기존 claims/key_numbers/core_message 유지).
    """
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
    # 95% 보존형 확장 필드 (모두 선택)
    atomic_claims:        list = field(default_factory=list)
    counter_arguments:    list = field(default_factory=list)
    examples:             list = field(default_factory=list)
    segments:             list = field(default_factory=list)
    conclusion_claim:     str = ""
    preservation_targets: list = field(default_factory=list)

    def to_pipeline_input(self) -> dict:
        """뉴스 파이프라인 SourceItemCreate 형식.

        body 구조:
          ① [95% 보존형 장문 작성 모드 헤더] — OpenAI 가 system 지시로 읽음
          ② [핵심 주장 / 결론 명제]          — Perplexity/Grok 자연 도달
          ③ [영상 분석 상세 + 확장 필드]     — full_analysis + atomic_claims 등
        """
        preservation_header = (
            "[YouTube 95% 보존형 장문 작성 모드]\n"
            "- 목표: 영상의 atomic claim 95% 이상 보존\n"
            "- 표면 문장 보존이 아니라 명제/논리/사례/반론/결론 보존\n"
            "- 발명 0건 — 영상에 없는 사실/숫자/장면/감정/인과 추가 금지\n"
            "- 결론 명제 동일 — 영상 결론과 같은 명제로 닫기\n"
            "- 첫 문장은 영상 안의 가장 강한 숫자/모순/고유명사/질문/위험 중에서 선택\n"
            "- 기본 구조 (hourglass):\n"
            "  1) 첫 화면: 핵심 stake\n"
            "  2) nut graf: 왜 지금 읽어야 하는지\n"
            "  3) 본문: claim graph 흐름 보존 (영상 순서 유지)\n"
            "  4) 사례/반론/결론 보존\n"
            "  5) 마지막: 영상 결론 명제와 동일하게 닫기\n"
            "- 스레드 분할 금지 (단일 X Premium 장문 포스트)\n"
            "- 글자수 제한 강제 금지\n"
            "- 작가/강사/저널리스트 기법은 배열/전환/이해/몰입에만 사용 — 새 사실 추가 금지\n"
            "- 발언자 인용은 큰따옴표 그대로\n"
            "- 출처(채널명·URL) 포스트 끝에 명시\n"
        )

        # 확장 필드 텍스트 블록 (있을 때만 추가, backward-compatible)
        extended_blocks: list[str] = []
        if self.conclusion_claim:
            extended_blocks.append(
                f"[결론 명제 (영상)]\n{self.conclusion_claim}"
            )
        if self.atomic_claims:
            lines = []
            for c in self.atomic_claims:
                if isinstance(c, dict):
                    ts = str(c.get("timestamp", "") or "")
                    text = str(c.get("claim", "") or "")
                    if not text:
                        continue
                    lines.append(f"- [{ts}] {text}" if ts else f"- {text}")
                elif isinstance(c, str) and c:
                    lines.append(f"- {c}")
            if lines:
                extended_blocks.append("[Atomic Claims]\n" + "\n".join(lines))
        if self.examples:
            lines = []
            for e in self.examples:
                if isinstance(e, dict):
                    text = str(e.get("example", "") or e.get("text", "") or "")
                    if text:
                        lines.append(f"- {text}")
                elif isinstance(e, str) and e:
                    lines.append(f"- {e}")
            if lines:
                extended_blocks.append("[사례]\n" + "\n".join(lines))
        if self.counter_arguments:
            lines = []
            for ca in self.counter_arguments:
                if isinstance(ca, dict):
                    text = str(ca.get("counter", "") or ca.get("text", "") or "")
                    if text:
                        lines.append(f"- {text}")
                elif isinstance(ca, str) and ca:
                    lines.append(f"- {ca}")
            if lines:
                extended_blocks.append("[반론]\n" + "\n".join(lines))
        if self.preservation_targets:
            lines = [
                f"- {t}" for t in self.preservation_targets
                if isinstance(t, str) and t
            ]
            if lines:
                extended_blocks.append("[보존 필수 항목]\n" + "\n".join(lines))

        extended_text = ("\n\n" + "\n\n".join(extended_blocks)) if extended_blocks else ""

        body = (
            f"{preservation_header}\n"
            f"[핵심 주장]\n{self.main_argument}\n\n"
            f"[요약]\n{self.downstream_summary or self.video_summary}\n\n"
            f"{self.full_analysis}"
            f"{extended_text}"
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


# ─── Gemini 분석 프롬프트 (v4 — 95% 보존형 claim graph 추출 모드) ─────
GEMINI_VIDEO_ANALYSIS_PROMPT = """[IDENTITY]
너는 영상 내용을 95% 이상 보존하기 위한 claim graph 추출 모듈이다.
요약가가 아니다. atomic claim, 사례, 반론, 결론 명제를 분리 추출한다.

[절대 금지]
- 요약 금지
- 압축 금지
- 해석 금지
- 개수 제한 금지
- 버리기 금지
- 재구성 금지
- 한국 현실·맥락 임의 추가 금지 (영상에서 발언자가 한국을 언급한 경우만 허용)
- 영상에 없는 사실/숫자/장면/감정/인과 추가 금지

[TASK]
이 영상에서 발언자가 실제로 한 말을 atomic claim 단위로 추출하고,
사례/반론/결론을 분리하며, 영상 순서와 결론 명제를 보존하라.

atomic claim = 더 쪼갤 수 없는 단일 명제 (한 문장 = 한 주장).
복합 문장은 여러 atomic claim 으로 분해한다.

추출 방법:
1. 영상 자막 전체를 읽어라
2. 발언자의 말을 원문에 가깝게 atomic claim 단위로 분해
3. 사례(example) 와 반론(counter_argument) 을 별도 분리
4. 결론 명제(conclusion_claim) 1줄로 추출 (영상 결론 그대로)
5. 영상 흐름을 segments 로 시간 순 분할 (선택)
6. 개수 제한 없이 전부 가져와라
7. 각 항목에 타임스탬프 포함

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
  "atomic_claims": [
    {
      "timestamp": "00:11",
      "claim": "단일 명제 1개 (쪼갤 수 없는 단위)",
      "depends_on": []
    }
  ],
  "examples": [
    {
      "timestamp": "03:42",
      "example": "발언자가 든 사례 원문"
    }
  ],
  "counter_arguments": [
    {
      "timestamp": "07:10",
      "counter": "발언자가 언급한 반론/예외/조건"
    }
  ],
  "segments": [
    {
      "timestamp": "00:00",
      "title": "도입",
      "summary_of_section": "섹션 요지 1줄 (발언자 말 그대로)"
    }
  ],
  "key_numbers": [
    {
      "value": "200달러",
      "context": "월 투자금",
      "timestamp": "01:23"
    }
  ],
  "core_message": "영상 전체의 핵심 메시지 1줄 (요약 아님, 발언자 말 그대로)",
  "conclusion_claim": "영상이 마지막에 닫는 결론 명제 1줄 (그대로)",
  "preservation_targets": [
    "반드시 본문에 보존해야 할 핵심 명제/숫자/사례 항목 리스트"
  ]
}

[SELF-CHECK]
□ atomic claim 단위로 분해했는가 (복합문 = 여러 claim)
□ 사례/반론/결론을 분리했는가
□ 결론 명제(conclusion_claim) 가 영상 마지막 결론과 동일한가
□ 영상 순서 보존했는가
□ 개수 제한 없이 전부 가져왔는가
□ 영상에 없는 내용 추가 안 했는가
□ 한국 맥락 임의 추가 안 했는가"""


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
            "maxOutputTokens": 32000,
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
            async with httpx.AsyncClient(timeout=300.0) as client:
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

            # v4 — claim graph 추출 (atomic_claims/사례/반론/결론 분리)
            claims = data.get("claims", []) or []
            key_numbers = data.get("key_numbers", []) or []
            core_message = str(data.get("core_message", "") or "")
            # v4 확장 필드 (없으면 빈 값 — backward-compatible)
            atomic_claims = data.get("atomic_claims", []) or []
            examples = data.get("examples", []) or []
            counter_arguments = data.get("counter_arguments", []) or []
            segments = data.get("segments", []) or []
            conclusion_claim = str(data.get("conclusion_claim", "") or "")
            preservation_targets = data.get("preservation_targets", []) or []
            # 리스트 타입 강제 (Gemini 가 dict 로 반환할 가능성 차단)
            if not isinstance(atomic_claims, list):
                atomic_claims = []
            if not isinstance(examples, list):
                examples = []
            if not isinstance(counter_arguments, list):
                counter_arguments = []
            if not isinstance(segments, list):
                segments = []
            if not isinstance(preservation_targets, list):
                preservation_targets = []

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
                atomic_claims=atomic_claims,
                examples=examples,
                counter_arguments=counter_arguments,
                segments=segments,
                conclusion_claim=conclusion_claim,
                preservation_targets=preservation_targets,
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
