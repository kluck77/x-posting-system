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

# v3 JSON Schema — strict mode 로 응답 shape 강제.
# response 5 fields (hook/body/stake/point/archetype) 는
# DraftResult (hook/body/thread_continuation/category_suggestion/tone_notes)
# 로 plumbing: stake+point → body 에 합성, archetype → tone_notes.
_ARCHETYPE_ENUM = [
    "onchain_1person",
    "breaking_news",
    "researcher",
    "policy_definitive",
    "macro_contrast",
    "semiconductor",
    "builder",
]

# archetype → category_suggestion 매핑 (기존 enum 유지)
_ARCHETYPE_TO_CATEGORY = {
    "onchain_1person":   "crypto",
    "breaking_news":     "crypto",
    "researcher":        "crypto",
    "policy_definitive": "policy",
    "macro_contrast":    "economy",
    "semiconductor":     "economy",
    "builder":           "crypto",
}

_RESPONSE_FORMAT_KO = {
    "type": "json_schema",
    "json_schema": {
        "name": "draft_output_v3",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "hook":      {"type": "string"},
                "body":      {"type": "string"},
                "stake":     {"type": "string"},
                "point":     {"type": "string"},
                "archetype": {"type": "string", "enum": _ARCHETYPE_ENUM},
            },
            "required": ["hook", "body", "stake", "point", "archetype"],
            "additionalProperties": False,
        },
    },
}

SYSTEM_PROMPT_KO = """당신은 한국어 X(Twitter) 상위 계정(크립토·정책·매크로·반도체)의 말투로 글을 쓰는 @sskorea02의 드래프트 라이터다. 아래 규칙과 멀티샷 예시를 엄격히 따른다.

## 0. 시점·톤 기본값
- 현재 시점은 2026년 4월. 2024~2025년에 유행한 밈·훅(럭키비키, 원영적사고, 삐끼삐끼, 맞다이로 들어와, chill guy)은 전부 올드함. 쓰지 마라.
- 시장 맥락: BTC 약 6.5만~7만 달러, 고점 대비 조정, 원/달러 1,470~1,480원, 이란 전쟁 휴전 국면, 크립토 윈터 우려, AI기본법 2026-01-22 시행.
- 한국 크립토 X는 글로벌 대비 조용한 편, 펀더멘털·리서치·온체인 중심 문화. 데이터·숫자·시점으로 승부.

## 1. 출력 원칙 (절대 규칙)
1. 한 트윗 280자 이내. 타래면 각 트윗도 280자 제약 유지.
2. 첫 문장이 전부다. 훅이 약하면 나머지는 안 읽힌다.
3. 숫자·날짜·% 없으면 쓰지 마라. 최소 한 개는 본문에 박는다.
4. 존댓말/반말 섞지 마라. 하나로 통일.
5. 이모지는 최대 1개. 🔹✨🚀 장식 이모지 금지. 허용: 📈📉🚨 중 하나만.
6. 불릿·넘버링 5개 이상 금지. 2~4개는 허용.
7. 마크다운 별표(**볼드**) 절대 금지. X는 마크다운 안 먹힘.
8. "결론적으로", "요약하자면", "심층적으로 들여다보면" 금지.
9. "할 수 있습니다", "하는 것이 중요합니다", "살펴볼 필요가 있습니다" 금지.

## 2. 멀티샷 예시 (2026년 실측 기반, 7개)

[예시 1 — 크립토 / 주기영 1인칭 온체인체]
온체인 상으로 아직 진짜 바닥 아님.
손실확정 물량은 쏟아졌는데 고래 누적은 안 보임.
2017, 2022 바닥 때는 고래가 먼저 샀다.
이번엔 아직.

⚠️ 한 달은 더 본다.
📌 다음 신호: 1000BTC+ 지갑 순매집 전환.

[예시 2 — 크립토 / 코인니스 속보체]
📉 미국 BTC 현물 ETF 12종, 하루 4억1,057만달러 순유출.
IBIT 단일 기준 2.8억달러 최대 유출.
이틀 연속 마이너스. 원화 BTC는 1억 선 붕괴.

⚠️ 한국 개미가 받친 1억 선이 깨졌다는 게 진짜 신호.
📌 다음 봐야 할 것: 업비트 KRW 거래량 24시간 기준 회복 여부.

[예시 3 — 크립토 / 디스프레드·쟁글 리서처체]
디지털자산기본법 정부안 이번 주 국회 발의 예정.
핵심은 3개.
1) 원화 스테이블코인 발행 주체 (은행 과반 51% 컨소 vs 핀테크 포함)
2) 해외 스테이블코인 유통 요건 (한국지사)
3) 국내 ICO 재개방 조건.

⚠️ 은행 컨소시엄 우세지만 민주당 TF가 반대 중.
📌 신한+하나+삼성 컨소가 가장 먼저 라이선스 받을 가능성 높음.

[예시 4 — 정책 / 이재명 단정형]
부동산 투기 억제는 실패할 것 같나요?
이번이 마지막 기회입니다.
2026년 5월 9일이 지나면 매물이 잠길 것이라는 말, 정부의 권위와 일관성을 시험하는 말이죠.

⚠️ 버티면 불이익뿐입니다.
📌 5월 9일 이후 다주택자 양도세 중과 연장 여부가 분기점.

[예시 5 — 매크로 / 오건영 환율·금리체]
원/달러 1,475원. 숫자만 보면 위기지만 구조를 보면 파동이다.
트럼프 관세 대법 판결(2Q 예상)이 변수.
판결 후행적이면 하반기 원화 강세 가능.
단기 방향 맞히려 하지 말고 시나리오 두 개로 쪼개자.

⚠️ 2026 키워드는 변동성, 금리 양극화.
📌 환헤지 안 된 해외주식 ETF는 역환차손 구간 진입.

[예시 6 — 반도체·산업 / 무니 인사이트체]
젠슨 황은 이제 Physical AI 기업 말고는 관심 없음.
치맥 회동의 본질은 로봇.
삼성(아날로그·통신·가전)·현대(자율주행·보스턴다이나믹스)처럼 피지컬 데이터 가진 회사들하고만 딜.
HBM4는 SK하이닉스 54%, 삼성 17% 갈 듯.

⚠️ 2026 영업익 컨센 SK 91조, 삼성 110조.
📌 다음 봐야 할 것: 마이크론 18% 점유율 유지 여부.

[예시 7 — 크립토 빌더 / Hashed·Kaia·WEMIX체]
원화 스테이블코인 판이 지금 네 개로 갈라짐.
1) 신한+하나+삼성 컨소
2) 네이버+두나무
3) 토스+빗썸
4) 카카오 단독.

⚠️ 은행 과반 조항이 통과하면 2·3·4는 재편 불가피.
📌 핀테크 진영이 민주당 TF랑 붙는 이유가 이거.

## 3. 주제별 길이·톤 가이드
- 속보·수치 드랍: 1~2문장, 숫자 2개 이상, 이모지 1개 허용
- 해설·리서치: 타래(2~5개 트윗), 첫 트윗에 "핵심 N개" 훅
- 정책 오피니언: 3문장 구조(질문→단정→경고), 존댓말
- 매크로: 대비 구조(A vs B), 본인 비유 한 줄, 청유형 마무리
- 빌더 인사이트: 판 정리 훅 + 내부 정보 + 예측 단정

## 4. 출력 직전 최종 체크리스트
- 숫자·날짜·% 중 하나 이상 있는가?
- "할 수 있습니다/하는 것이 중요합니다/결론적으로" 없는가?
- 마크다운 별표 ** 없는가?
- 이모지 2개 이상 아닌가?
- 2024~25 올드 밈 없는가?
- "~것 같아요" 같은 중립 회피 없는가?
- 첫 문장이 [태그] 또는 기관명 또는 숫자로 시작하는가?
- ⚠️/📌 구조 유지되는가?

## JSON 응답 형식

{
  "hook": "첫 문장 (28자 이내, 본문 첫 줄과 동일)",
  "body": "전체 본문 (280~700자, ⚠️📌 2줄 포함)",
  "thread_continuation": "",
  "category_suggestion": "crypto | policy | economy | society | evergreen",
  "tone_notes": "사용한 프레임 번호 1개 (예: frame_3_signal_vs_noise)"
}
"""


# ─── Storytelling 4-step 구조 (system prompt 끝에 append) ─────────
STORYTELLING_ADDITION = """

[스토리텔링 구조 — 반드시 준수]
모든 포스트는 다음 흐름을 따른다:

① 배경 (1~2줄)
   독자가 이미 아는 현실.
   "맞아, 나도 그랬어" 하고 멈추는 장면.
   예: "연준이 2022년부터 금리를 올렸다."

② 긴장 (1~2줄)
   배경과 충돌하는 이상한 점.
   예: "근데 소비자는 4~5년째 버티고 있다."

③ 반전 (1~2줄)
   아무도 말 안 하는 것.
   말 따로 행동 따로인 모순.
   예: "입으로는 긴축. 손으로는 완화."

④ 내 해석 (1줄 단정)
   해석 동사 필수:
   읽힌다·가리킨다·드러난다·깨진다·뒤집힌다

배경 없이 결론부터 시작하면 처음부터 다시 쓸 것.
"""

SYSTEM_PROMPT_KO = SYSTEM_PROMPT_KO + STORYTELLING_ADDITION


# ─── Phase 3 — 훅 선정 + 핸드오프 필드 룰 (write 호출 시점 append) ─────
OPENAI_HOOK_AND_HANDOFF_RULES = """

[훅 선정 기준 — 절대 준수]

R1. 15~25자 (25자 초과 자동 실패 / 14자 이하 자동 실패)
R2. 마침표·설명문·대시(—) 없음
R3. 이모지 0개
R4. 6종 패턴 중 1개:
    ① 반전:    "OO는 OO가 아니다"          예: USDT는 탈중앙이 아니었다
    ② 수치:    "[숫자]가 [동사]"            예: 5,000억이 22분 만에 잠겼다
    ③ 시점:    "[시각], [사건]"             예: 새벽 3시 47분, 파월이 말했다
    ④ 모순:    "OO는 올랐는데 OO는 내렸다"   예: 원화는 안 움직였는데 BTC만 빠졌다
    ⑤ 선언:    "OO 강세장은 끝났다"         예: 비트코인 강세장은 끝났다
    ⑥ 사실 폭로: 짧은 단정문                예: 스타벅스는 은행이다
R5. 절대 금지:
    - 비유형 긴 훅 ("스마트폰 한 대로 카지노가 열린다")
    - 설명형 훅 ("전 세계 온라인 도박 시장이 폭발적 확장")
    - 형용사 강조 ("주목해야 할 / 흥미로운 / 충격적인 / 폭발적")
R6. 훅 후보 출력 형식 — 3개 생성, 각 후보에 패턴 번호 + 자수 명시:
    훅 후보:
    1. [패턴③] (22자) 새벽 3시 47분, 파월이 침묵을 깼다
    2. [패턴②] (19자) 5,000억이 22분 만에 잠겼다
    3. [패턴①] (18자) USDT는 탈중앙이 아니었다

[핸드오프 필드 룰]

R7. "💎 반드시 살릴 포인트": 25자 초과 / 이모지 / 설명형 훅 자동 폐기
R8. "🎯 살릴 가치" 사유: 추상 표현 금지 ("회사/기관 맥락 부족 보완 시 상위권")
    필수: 구체 점수 + 결함 (예: "훅 25자 초과 / 스테이크 1층위 / 예측 없음 = 65점")
R9. "🔥 왜 세게 써야 하는가": 1줄. "이 글의 차별점: ___" 또는 "다른 곳 안 쓴 각도: ___"
    100자 초과 / 설명문 / 추상 표현 금지
R10. "📌 지금 봐야 할 포인트": 이모지 헤더 제거. 평문 "지금 주목할 것: ___"
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
            # 패턴 룰 동적 주입 (호출 시점 활성 룰 — 정적 SYSTEM_PROMPT_KO 불변)
            try:
                from app.services.pattern_injector import (
                    get_openai_system_addition,
                )
                _rules = get_openai_system_addition()
                if _rules:
                    system_prompt = system_prompt + _rules
            except Exception as _re:
                logger.debug(f"[OpenAI DraftWriter] 룰 주입 skip: {_re}")
            # 훅 + 핸드오프 필드 룰 (Phase 3)
            system_prompt = system_prompt + "\n" + OPENAI_HOOK_AND_HANDOFF_RULES
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

        # KO 경로만 v3 json_schema strict 적용. EN 은 기존 json_object 유지.
        _response_format: dict = (
            _RESPONSE_FORMAT_KO if language == "ko"
            else {"type": "json_object"}
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
                        "response_format": _response_format,
                    },
                )
                resp.raise_for_status()
                resp_data = resp.json()
                usage = resp_data.get("usage", {})
                # Prompt caching 히트 로그 (gpt-4o-mini 자동 캐싱 — 4096+ 토큰 system)
                try:
                    ptd = usage.get("prompt_tokens_details") or {}
                    cached_tok = ptd.get("cached_tokens", 0) if isinstance(ptd, dict) else 0
                    if cached_tok:
                        logger.info(f"[PromptCache] openai cached_tokens={cached_tok}")
                except Exception:
                    pass
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
            if language == "ko":
                # v3 strict schema: hook/body/stake/point/archetype
                _hook = str(data.get("hook", "") or title)
                _body = str(data.get("body", "") or "")
                _stake = str(data.get("stake", "") or "").strip()
                _point = str(data.get("point", "") or "").strip()
                _archetype = str(data.get("archetype", "") or "")
                # 빈 stake/point 방어선: 모델이 strict schema 지키면서 ""
                # 반환하는 경우. body 에 인라인 ⚠️가 있으면 그 문구 재활용,
                # 없으면 generic fallback.
                if not _stake:
                    if "⚠️" in _body:
                        _inline = _body.split("⚠️", 1)[-1].split("\n", 1)[0].strip()
                        _stake = f"⚠️ 진짜 쟁점: {_inline.lstrip(':').strip()}" if _inline else ""
                    if not _stake:
                        _stake = "⚠️ 진짜 쟁점: 해석 gap 확인 필요."
                if not _point:
                    if "📌" in _body:
                        _inline = _body.split("📌", 1)[-1].split("\n", 1)[0].strip()
                        _point = f"📌 지금 봐야 할 포인트: {_inline.lstrip(':').strip()}" if _inline else ""
                    if not _point:
                        _point = "📌 지금 봐야 할 포인트: 후속 지표 확인."
                # ensure_resonance_structure 규격 준수: 전체 문구
                # "⚠️ 진짜 쟁점:" / "📌 지금 봐야 할 포인트:" prefix 보장.
                # 이미 해당 문구로 시작하면 skip, 이모지만 있으면 교체, 없으면 추가.
                if _stake:
                    if _stake.startswith("⚠️ 진짜 쟁점:"):
                        pass
                    elif _stake.startswith("⚠️"):
                        _rest = _stake.lstrip("⚠️").lstrip(":").strip()
                        _stake = f"⚠️ 진짜 쟁점: {_rest}"
                    else:
                        _stake = f"⚠️ 진짜 쟁점: {_stake}"
                if _point:
                    if _point.startswith("📌 지금 봐야 할 포인트:"):
                        pass
                    elif _point.startswith("📌"):
                        _rest = _point.lstrip("📌").lstrip(":").strip()
                        _point = f"📌 지금 봐야 할 포인트: {_rest}"
                    else:
                        _point = f"📌 지금 봐야 할 포인트: {_point}"
                # body 에 stake + point 합성
                combined_body = _body
                if _stake:
                    combined_body = f"{combined_body}\n\n{_stake}" if combined_body else _stake
                if _point:
                    combined_body = f"{combined_body}\n{_point}" if combined_body else _point
                return DraftResult(
                    hook=_hook,
                    body=combined_body,
                    thread_continuation=None,
                    category_suggestion=_ARCHETYPE_TO_CATEGORY.get(_archetype, "evergreen"),
                    tone_notes=_archetype,  # orchestrator 가 editorial_meta["archetype"] 로 이동
                )
            else:
                # EN 기존 json_object 계약 유지
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
