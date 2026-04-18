"""
비전 서비스
===========
텔레그램으로 보낸 사진/스크린샷에서 텍스트와 핵심 내용을 추출합니다.
Claude Vision(Anthropic) API를 사용합니다.

지원 입력:
  - 뉴스 기사 스크린샷
  - 커뮤니티 게시글 캡쳐 (DCInside, FMKorea 등)
  - 차트/그래프 (숫자 설명)
  - 일반 텍스트 이미지
"""

import base64
import logging
import httpx
from app.config import settings

logger = logging.getLogger(__name__)

CLAUDE_API_URL = "https://api.anthropic.com/v1/messages"
VISION_MODEL = "claude-sonnet-4-20250514"

VISION_SYSTEM = """당신은 이미지에서 텍스트와 핵심 내용을 추출하는 도우미입니다.

입력 유형별 처리:
- 뉴스 기사: 제목, 핵심 내용, 날짜, 숫자 데이터 추출
- 커뮤니티 게시글(DCInside, FMKorea 등): 제목, 본문 요약, 주요 댓글 반응(닉네임 제외)
- 차트/그래프: 수치와 트렌드 설명
- SNS 게시글: 핵심 주장과 반응

규칙:
- 닉네임, 아이디, 개인정보 절대 포함하지 말 것
- 욕설은 [비속어]로 대체
- 원문 그대로 번역/추출 (해석 최소화)
- 한국어로 답변"""

VISION_PROMPT = """이 이미지의 내용을 추출해줘.

다음 형식으로:
제목: [기사/게시글 제목 또는 주요 주제]
유형: [뉴스기사 / 커뮤니티게시글 / 차트 / SNS / 기타]
핵심내용: [2-3줄 요약]
주요수치: [숫자/날짜/퍼센트 등 있으면]
반응/댓글: [있으면 익명으로 요약]"""


async def extract_from_image(image_bytes: bytes, mime_type: str = "image/jpeg") -> dict:
    """
    이미지에서 텍스트와 핵심 내용을 추출합니다.

    Args:
        image_bytes: 이미지 바이트 데이터
        mime_type: 이미지 MIME 타입 (image/jpeg, image/png 등)

    Returns:
        {
            "title": str,       # 추출된 제목
            "text": str,        # 전체 추출 텍스트
            "content_type": str, # 감지된 유형 (뉴스기사/커뮤니티게시글/...)
            "raw": str,         # Claude 원본 응답
            "error": str | None,
        }
    """
    if not settings.has_anthropic:
        logger.warning("Anthropic 키 없음 — 이미지 텍스트 추출 불가")
        return {
            "title": "이미지 입력",
            "text": "[Anthropic API 키가 없어 이미지 분석 불가. 텍스트로 직접 내용을 입력해주세요.]",
            "content_type": "unknown",
            "raw": "",
            "error": "anthropic_key_missing",
        }

    try:
        image_b64 = base64.standard_b64encode(image_bytes).decode("utf-8")

        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                CLAUDE_API_URL,
                headers={
                    "x-api-key": settings.anthropic_api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": VISION_MODEL,
                    "max_tokens": 1500,
                    "system": VISION_SYSTEM,
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "image",
                                    "source": {
                                        "type": "base64",
                                        "media_type": mime_type,
                                        "data": image_b64,
                                    },
                                },
                                {"type": "text", "text": VISION_PROMPT},
                            ],
                        }
                    ],
                },
            )
            resp.raise_for_status()
            resp_data = resp.json()
            usage = resp_data.get("usage", {})
            logger.info(
                f"[API-COST] anthropic {VISION_MODEL} "
                f"in={usage.get('input_tokens', '?')} "
                f"out={usage.get('output_tokens', '?')} "
                f"caller=Vision"
            )
            try:
                from app.services.api_cost_tracker import record_usage
                record_usage("anthropic", VISION_MODEL, "Vision",
                             usage.get("input_tokens", 0), usage.get("output_tokens", 0))
            except Exception:
                pass
            raw = resp_data["content"][0]["text"]

        # 제목 추출 시도
        title = "이미지 분석 결과"
        content_type = "기타"
        for line in raw.splitlines():
            if line.startswith("제목:"):
                title = line.replace("제목:", "").strip()[:200]
            elif line.startswith("유형:"):
                content_type = line.replace("유형:", "").strip()

        logger.info(f"이미지 분석 완료: 유형={content_type}, 제목='{title[:50]}'")
        return {
            "title": title,
            "text": raw,
            "content_type": content_type,
            "raw": raw,
            "error": None,
        }

    except Exception as e:
        err = str(e)[:200]
        logger.error(f"이미지 분석 오류: {err}")
        return {
            "title": "이미지 입력",
            "text": f"[이미지 분석 실패: {err}]",
            "content_type": "unknown",
            "raw": "",
            "error": err,
        }
