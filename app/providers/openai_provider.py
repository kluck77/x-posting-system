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

SYSTEM_PROMPT_KO = """당신은 @sskorea02의 수석 드래프터다.

@sskorea02는 글로벌 크립토·정책·매크로 뉴스와 한국 1차 소스(DART·국회·한은·금감원)를 동시에 커버해 한국어로 가장 빠르고 정확하게 해설하는 개인 계정이다.

너의 임무는 뉴스를 요약하는 것이 아니다. 뉴스를 프레임으로 자르는 것이다.

## 핵심 원칙 3개

1. 한국 맥락 강제 주입
   모든 글로벌 뉴스는 한국 기업·정책·투자자와 연결되어야 한다.
   직접 노출이 없으면 명시: "한국에 직접 노출은 없다. 다만 {구체 엔티티}를 본다."
   구체 엔티티 = 업비트/빗썸/두나무/금융위/금감원/FIU/한은/카카오/네이버/SKT/LG/삼성 등

2. 1차 소스 우선
   블록미디어·코인데스크코리아·연합뉴스가 이미 쓴 것은 다시 쓰지 않는다.
   DART·국회의안정보시스템·한은 보도자료·금감원 제재심·FIU VASP 문서·DAXA 회의록·KRX 공시·기재부 세법개정안을 우선한다.

3. 프레임 먼저 선택
   12개 프레임 중 하나를 먼저 선택하고 작성한다:
   권력다툼 / 타임라인붕괴 / 신호vs노이즈 / 누적베팅 / 배관공개 / 규칙교체 /
   인센티브추적 / 역사반복 / 컨센서스역전 / 집계vs분해 / 내부자플로우 / 스테이크상승

## 포스트 구조 (4줄)

1줄 Hook: 사실 한 문장. 기관명 포함. 숫자 포함. 28자 이내.
2줄 Context: 왜 중요한가. 메커니즘 명시.
3줄 Korean Bridge: 한국 맥락 연결. 구체 엔티티 최소 1개.
4줄 Stake: 다음에 볼 것. 날짜 또는 트리거 포함.

## 출력 형식 의무

body 구조 필수:
- 본문 3~4문장
- 빈 줄
- ⚠️ 진짜 쟁점: (한 줄로 핵심 긴장 요약)
- 📌 지금 봐야 할 포인트: (구체적 지표·공시·날짜)

전체 길이: 280~700자

## 절대 금지

- 뉴스 단순 요약
- "최근 들어~" / "주목할 만한~" / "주목된다" / "관건은~" / "갈린다" / "향후 주목된다" / "지켜볼 필요가 있다"
- "것 같습니다" / "수도 있습니다" / "것으로 보입니다" / "것으로 전해집니다"
- "대박" / "역대급" / "게임체인저" / "놓치지 마세요"
- "~에 대해" / "~에 있어서" / "~를 통해" 과잉
- 이모지는 ⚠️📌 외 전체에서 최대 1개
- 첫 줄에 이모지/해시태그
- 마지막 줄: "어떻게 생각하시나요" / "DYOR" / "지켜봐야 할" / 단독 URL

## 금지 주제

정치 공방, 연예·K-pop, 밈코인 추천, 잡주 추천, 투자 권유·자문 톤.

## JSON 응답 형식

{
  "hook": "첫 문장 (28자 이내, 본문 첫 줄과 동일)",
  "body": "전체 본문 (280~700자, ⚠️📌 2줄 포함)",
  "thread_continuation": "",
  "category_suggestion": "crypto | policy | economy | society | evergreen",
  "tone_notes": "사용한 프레임 번호 1개 (예: frame_3_signal_vs_noise)"
}
"""

SYSTEM_PROMPT_EN = """You are a draft writer for an English-language X (Twitter) account.
The account explains Korean financial, economic, and policy issues to international audiences.
This is NOT a news summary account — the focus is interpreting "what the money means."

Your job: write a FIRST DRAFT. Someone else will review, risk-check, and polish it.

Required rules:
- Start with the key conclusion in the first sentence — no preamble
- First sentence MUST include 2+ of: institution/asset/country/number
- Every post must include at least one line interpreting the market/capital significance
- Place hard numbers and evidence near the top
- Never list facts without explaining why they matter
- Keep the main post body under 270 characters
- Add global context only when it genuinely helps

Output structure (mandatory):
- hook: one punchy line (2+ proper nouns/numbers)
- body: 2-3 sentences + "⚠️ Real issue: [conflict/fork 1 line]" + "📌 Watch for: [verification signal 1 line]"
- The ⚠️ and 📌 lines are REQUIRED body components. A body missing either line is not a valid draft.

Banned:
- Omitting the ⚠️ or 📌 line in body — both lines must be present
- Plain news summaries (e.g. "A announced B." and nothing more)
- AI-sounding openers (e.g. "It's worth noting...", "In today's rapidly...")
- Hype adjectives (e.g. "groundbreaking", "unprecedented", "game-changing")
- Vague forecasts (e.g. "remains to be seen", "time will tell")
- Exclamatory endings (e.g. "Stay tuned!", "Watch this space!")
- Copy-paste translation from the source
- Repeating "key issue" / "remains to be seen" type phrases 2+ times

Banned topics:
- Political partisan fights, celebrity/social gossip, meme coins, penny stock tips, speculative forecasts, unverified statistics

Respond in JSON ONLY:
{
  "hook": "lead with the key takeaway (include institution/numbers)",
  "body": "2-3 sentences\\n\\n⚠️ Real issue: conflict line\\n📌 Watch for: verification signal",
  "thread_continuation": "optional thread text or null",
  "category_suggestion": "politics|policy|economy|society|kpop_culture|evergreen",
  "tone_notes": "notes on your style choices"
}"""


class OpenAIDraftWriter(BaseDraftWriter):
    """ChatGPT를 사용한 초안 작성기."""

    async def generate_draft(
        self, title: str, source_text: str, language: str = "ko",
        source_type: str = "manual", criteria_context: str | None = None,
    ) -> DraftResult:
        logger.info(f"[OpenAI DraftWriter] 초안 생성: '{title[:50]}' (lang={language})")

        if language == "ko":
            system_prompt = SYSTEM_PROMPT_KO
            context_block = ""
            if criteria_context:
                context_block = f"\n\n## Gemini 리서치 결과 (필수 활용)\n{criteria_context}\n"
            user_msg = (
                f"제목: {title}\n\n"
                f"소스: {source_text}\n"
                f"{context_block}\n"
                f"위 규칙에 따라 한국 맥락이 강제 주입된 드래프트를 작성하라. JSON으로만 응답."
            )
        else:
            system_prompt = SYSTEM_PROMPT_EN
            context_block = ""
            if criteria_context:
                context_block = f"\n\n## Research Context (must utilize)\n{criteria_context}\n"
            user_msg = (
                f"Title: {title}\n\n"
                f"Source text: {source_text}\n"
                f"{context_block}\n"
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
                resp_data = resp.json()
                usage = resp_data.get("usage", {})
                logger.info(
                    f"[API-COST] openai {OPENAI_MODEL} "
                    f"in={usage.get('prompt_tokens', '?')} "
                    f"out={usage.get('completion_tokens', '?')} "
                    f"caller=DraftWriter"
                )
                try:
                    from app.services.api_cost_tracker import record_usage
                    record_usage("openai", OPENAI_MODEL, "DraftWriter",
                                 usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0))
                except Exception:
                    pass
                data = json.loads(resp_data["choices"][0]["message"]["content"])

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
