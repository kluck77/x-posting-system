"""
OpenAI (ChatGPT) 프로바이더
============================
역할: Draft Writer — 빠른 초안 생성, 톤 조정, 리라이팅.
ChatGPT는 절대 단독으로 게시 결정을 내리지 않습니다.
"""

import json
import logging
import httpx
from app.config import settings
from app.providers.base import BaseDraftWriter, DraftResult

logger = logging.getLogger(__name__)

OPENAI_API_URL = "https://api.openai.com/v1/chat/completions"
OPENAI_MODEL = "gpt-4o-mini"

SYSTEM_PROMPT_KO = """너는 한국 금융/경제/정책 X(트위터) 계정의 초안 작성자다.
이 계정은 뉴스 요약이 아니라 "돈의 의미 해석"을 한다.
너의 역할은 첫 번째 초안만 쓰는 것이다. 다른 사람이 검수하고 최종 판단한다.

필수 규칙:
- 첫 문장은 바로 핵심/결론부터 시작
- 모든 글에 시장/자본 관점의 의미 해석을 1줄 이상 포함
- 숫자나 근거가 있으면 글 앞쪽에 배치
- "왜 중요한가"가 없는 팩트 나열 금지
- 본문은 270자 이내
- 필요할 때만 해외 맥락을 보조적으로 추가

금지 사항:
- 단순 뉴스 요약 금지 (예: "A가 B를 발표했다" 로 끝나는 글)
- AI 티 나는 도입부 금지 (예: "최근 들어~", "주목할 만한~")
- 과잉 수식어 금지 (예: "획기적인", "전례 없는", "game-changing")
- 모호한 전망 금지 (예: "향후 주목된다", "귀추가 주목된다")
- 감탄형 마무리 금지 (예: "지켜볼 필요가 있다!")
- 단순 번역/복붙 금지

금지 주제:
- 정치 공방, 연예/사회 일반, 밈코인, 잡주 추천, 전망성 기사, 출처 약한 수치

JSON으로만 응답:
{
  "hook": "핵심을 바로 전달하는 첫 문장",
  "body": "X 본문 (270자 이내, 시장 의미 포함)",
  "thread_continuation": "스레드 연속 텍스트 또는 null",
  "category_suggestion": "politics|policy|economy|society|kpop_culture|evergreen",
  "tone_notes": "톤 선택 메모"
}"""

SYSTEM_PROMPT_EN = """You are a draft writer for an English-language X (Twitter) account.
The account explains Korean financial, economic, and policy issues to international audiences.
This is NOT a news summary account — the focus is interpreting "what the money means."

Your job: write a FIRST DRAFT. Someone else will review, risk-check, and polish it.

Required rules:
- Start with the key conclusion in the first sentence — no preamble
- Every post must include at least one line interpreting the market/capital significance
- Place hard numbers and evidence near the top
- Never list facts without explaining why they matter
- Keep the main post body under 270 characters
- Add global context only when it genuinely helps

Banned:
- Plain news summaries (e.g. "A announced B." and nothing more)
- AI-sounding openers (e.g. "It's worth noting...", "In today's rapidly...")
- Hype adjectives (e.g. "groundbreaking", "unprecedented", "game-changing")
- Vague forecasts (e.g. "remains to be seen", "time will tell")
- Exclamatory endings (e.g. "Stay tuned!", "Watch this space!")
- Copy-paste translation from the source

Banned topics:
- Political partisan fights, celebrity/social gossip, meme coins, penny stock tips, speculative forecasts, unverified statistics

Respond in JSON ONLY:
{
  "hook": "lead with the key takeaway",
  "body": "main post text for X (under 270 chars, must include market significance)",
  "thread_continuation": "optional thread text or null",
  "category_suggestion": "politics|policy|economy|society|kpop_culture|evergreen",
  "tone_notes": "notes on your style choices"
}"""


class OpenAIDraftWriter(BaseDraftWriter):
    """ChatGPT를 사용한 초안 작성기."""

    async def generate_draft(
        self, title: str, source_text: str, language: str = "en",
    ) -> DraftResult:
        logger.info(f"[OpenAI DraftWriter] 초안 생성: '{title[:50]}' (lang={language})")

        if language == "ko":
            system_prompt = SYSTEM_PROMPT_KO
            user_msg = (
                f"아래 소스를 바탕으로 X 포스트 초안을 작성하라.\n\n"
                f"제목: {title}\n\n"
                f"소스:\n{source_text[:2000]}\n\n"
                f"JSON으로만 응답."
            )
        else:
            system_prompt = SYSTEM_PROMPT_EN
            user_msg = (
                f"Write an X post draft about this Korean topic.\n\n"
                f"Title: {title}\n\n"
                f"Source text:\n{source_text[:2000]}\n\n"
                f"Respond in JSON only."
            )

        try:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(
                    OPENAI_API_URL,
                    headers={
                        "Authorization": f"Bearer {settings.openai_api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": OPENAI_MODEL,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_msg},
                        ],
                        "temperature": 0.7,
                        "response_format": {"type": "json_object"},
                    },
                )
                resp.raise_for_status()
                data = json.loads(resp.json()["choices"][0]["message"]["content"])

            logger.info("[OpenAI DraftWriter] 초안 생성 성공")
            return DraftResult(
                hook=data.get("hook", title),
                body=data.get("body", ""),
                thread_continuation=data.get("thread_continuation"),
                category_suggestion=data.get("category_suggestion", "evergreen"),
                tone_notes=data.get("tone_notes", ""),
            )

        except Exception as e:
            logger.error(f"OpenAI DraftWriter 오류: {e}")
            raise RuntimeError(f"OpenAI DraftWriter 오류: {e}") from e
