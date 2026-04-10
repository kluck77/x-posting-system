"""
Anthropic (Claude) 프로바이더
==============================
역할 2가지:
  - Draft Writer (대안): Claude도 초안을 쓸 수 있음
  - Reviewer (주역할): 리스크 판단, 팩트 체크, 최종 다듬기, 안전 검토

Claude는 시스템의 "두뇌" 역할입니다.
구조, 신뢰성, 안전 로직을 책임집니다.
"""

import json
import logging
import httpx
from app.config import settings
from app.providers.base import (
    BaseDraftWriter, BaseReviewer,
    DraftResult, ReviewResult, ResearchResult, FactCheckResult,
)

logger = logging.getLogger(__name__)

CLAUDE_API_URL = "https://api.anthropic.com/v1/messages"
CLAUDE_MODEL = "claude-sonnet-4-20250514"

# --- Draft Writer 시스템 프롬프트 ---
DRAFT_SYSTEM_PROMPT_KO = """너는 한국 금융/경제/정책 X(트위터) 계정의 초안 작성자다.
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
- 과잉 수식어 금지 (예: "획기적인", "전례 없는")
- 모호한 전망 금지 (예: "향후 주목된다")
- 감탄형 마무리 금지
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

DRAFT_SYSTEM_PROMPT_EN = """You are a draft writer for an English-language X account that explains Korean financial, economic, and policy issues to international audiences.
This is NOT a news summary account — the focus is interpreting "what the money means."
Write a first draft. Someone else will review and finalize.

Required rules:
- Start with the key conclusion — no preamble
- Include at least one line on market/capital significance
- Place numbers and evidence near the top
- Never list facts without explaining why they matter
- Keep post body under 270 characters

Banned:
- Plain news summaries, AI-sounding openers, hype adjectives, vague forecasts, exclamatory endings, copy-paste translation

Respond in JSON ONLY:
{
  "hook": "lead with the key takeaway",
  "body": "main post text for X (under 270 chars, must include market significance)",
  "thread_continuation": "optional thread text or null",
  "category_suggestion": "politics|policy|economy|society|kpop_culture|evergreen",
  "tone_notes": "style notes"
}"""

# --- Reviewer 시스템 프롬프트 ---
REVIEW_SYSTEM_PROMPT = """너는 한국어 X(트위터) 계정의 편집 리뷰어이자 안전 판단 두뇌다.
이 계정은 한국 금융/경제/정책 이슈를 다루며, "돈의 의미 해석"에 집중한다.

초안과 선택적 리서치/팩트체크 데이터를 받는다. 너의 역할:
1. 팩트를 가능한 범위에서 검증
2. 미확인 사항은 불확실로 표시
3. 위험도 판단: low / medium / high
4. 초안을 매끄럽고 균형 잡힌 포스트로 다듬기
5. 본문 270자 이내 유지
6. 품질 플래그 태깅 (아래 참조)

품질 플래그 — 해당하는 모든 플래그를 태깅 (없으면 빈 리스트):
- ai_smell: 로봇 같은 문체, AI 티 나는 표현 ("최근 들어~", "주목할 만한~", "In a move that")
- summary_only: 관점이나 인사이트 없이 팩트만 나열
- market_link: 시장/경제적 영향 연결이 빠짐
- verbose: 본문 270자 초과 또는 불필요하게 장황
- speculation: 근거 없는 예측이나 의견을 사실처럼 기술
- banned_topic: 북한 군사작전, 아이돌 연애 루머, 자살 세부사항
- follow_worthy: 팔로우할 이유가 되는 독특한 관점
- actionable: 독자가 행동할 수 있는 정보 (투자, 회피, 준비)
- banned_style: 해시태그, 이모지, "속보:", 클릭베이트 대문자

엄격한 안전 규칙:
- 정치 / 정책 / 경제 / 사회 / K-POP 논란 → 반드시 medium 또는 high
- 에버그린 교육 콘텐츠 → low 가능
- 미확인 루머 절대 포함 금지
- 선정적 표현 절대 금지

hook과 body는 반드시 한국어로 작성하라. 단, 입력이 영어(language=en)인 경우에만 영어로 작성.
risk_reasoning과 ai_rationale은 항상 한국어로 작성하라.

JSON으로만 응답:
{
  "hook": "최종 훅 (한국어)",
  "body": "최종 본문 (270자 이내, 한국어)",
  "thread_continuation": "스레드 연속 또는 null",
  "category": "politics|policy|economy|society|kpop_culture|evergreen",
  "risk_level": "low|medium|high",
  "risk_reasoning": "이 위험도를 선택한 이유 (한국어)",
  "ai_rationale": "이 초안이 독자에게 가치 있는 이유 (한국어)",
  "recommended_action": "approve|review|reject",
  "quality_flags": ["flag1", "flag2"]
}""""""


class AnthropicDraftWriter(BaseDraftWriter):
    """Claude를 사용한 초안 작성기 (대안 드래프트 역할)."""

    async def generate_draft(
        self, title: str, source_text: str, language: str = "ko",
    ) -> DraftResult:
        logger.info(f"[Claude DraftWriter] 초안 생성: '{title[:50]}' (lang={language})")

        if language == "ko":
            system_prompt = DRAFT_SYSTEM_PROMPT_KO
            user_msg = (
                f"아래 소스를 바탕으로 X 포스트 초안을 작성하라.\n\n"
                f"제목: {title}\n소스:\n{source_text[:2000]}\n"
                f"JSON으로만 응답."
            )
        else:
            system_prompt = DRAFT_SYSTEM_PROMPT_EN
            user_msg = (
                f"Write an X post draft.\n\n"
                f"Title: {title}\nSource:\n{source_text[:2000]}\n"
                f"Respond in JSON only."
            )

        content = await self._call_claude(system_prompt, user_msg)
        data = json.loads(content)
        return DraftResult(
            hook=data.get("hook", title),
            body=data.get("body", ""),
            thread_continuation=data.get("thread_continuation"),
            category_suggestion=data.get("category_suggestion", "evergreen"),
            tone_notes=data.get("tone_notes", ""),
        )

    async def _call_claude(self, system: str, user_msg: str) -> str:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                CLAUDE_API_URL,
                headers={
                    "x-api-key": settings.anthropic_api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": CLAUDE_MODEL,
                    "max_tokens": 1024,
                    "system": system,
                    "messages": [{"role": "user", "content": user_msg}],
                },
            )
            resp.raise_for_status()
            return resp.json()["content"][0]["text"]


class AnthropicReviewer(BaseReviewer):
    """Claude를 사용한 리뷰어 (메인 역할)."""

    async def review_and_refine(
        self,
        title: str,
        source_text: str,
        draft: DraftResult,
        research: ResearchResult | None = None,
        factcheck: FactCheckResult | None = None,
        criteria_context: str | None = None,
    ) -> ReviewResult:
        logger.info(f"[Claude Reviewer] 리뷰: '{title[:50]}'")

        user_msg = (
            f"## Source\nTitle: {title}\nText: {source_text[:1500]}\n\n"
            f"## Draft to Review\nHook: {draft.hook}\nBody: {draft.body}\n"
            f"Thread: {draft.thread_continuation or 'none'}\n"
            f"Suggested category: {draft.category_suggestion}\n\n"
        )
        if research:
            user_msg += (
                f"## Research\nSummary: {research.summary[:500]}\n"
                f"Facts: {'; '.join(research.key_facts[:5])}\n\n"
            )
        if factcheck:
            user_msg += (
                f"## Fact Check\nVerified: {factcheck.verified}\n"
                f"Corrections: {'; '.join(factcheck.corrections[:3])}\n\n"
            )
        user_msg += "리뷰하고 다듬어라. JSON으로만 응답. hook과 body는 한국어로 작성."

        try:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(
                    CLAUDE_API_URL,
                    headers={
                        "x-api-key": settings.anthropic_api_key,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                    json={
                        "model": CLAUDE_MODEL,
                        "max_tokens": 1024,
                        "system": REVIEW_SYSTEM_PROMPT,
                        "messages": [{"role": "user", "content": user_msg}],
                    },
                )
                resp.raise_for_status()
                content = resp.json()["content"][0]["text"]
                data = json.loads(content)

            logger.info(f"[Claude Reviewer] 완료: risk={data.get('risk_level')}")
            quality_flags = data.get("quality_flags", [])
            rationale = data.get("ai_rationale", "")
            if quality_flags:
                rationale += f" [flags: {','.join(quality_flags)}]"

            return ReviewResult(
                hook=data.get("hook", draft.hook),
                body=data.get("body", draft.body),
                thread_continuation=data.get("thread_continuation"),
                category=data.get("category", "evergreen"),
                risk_level=data.get("risk_level", "medium"),
                risk_reasoning=data.get("risk_reasoning", ""),
                ai_rationale=rationale,
                recommended_action=data.get("recommended_action", "review"),
            )
        except Exception as e:
            logger.error(f"Claude Reviewer 오류: {e}")
            raise RuntimeError(f"Claude Reviewer 오류: {e}") from e
