# CLAUDE_CODE_HANDOFF.md
# Claude Code 작업 인수인계 문서
# 작성: Perplexity Computer (코드 전체 검토 후 작성)
# 기준: 2026-04-06
# 이 문서는 GPT가 프롬프트를 짤 때도 참고 기준으로 쓴다

---

## 변경 이력 (Change Log)

| 버전 | 날짜 | 파일 | 내용 |
|------|------|------|------|
| v11a | 2026-04-07 | `telegram_service.py`, `telegram_bot.py` | Telegram 카드 영역 오버라이드 (v10 → v11): 카드 필드 순서 재배치 (Hook→Post→Risk→Why→Verdict 우선), mock 게시 오인 문구 수정 ("POSTED TO X" / "APPROVED & POSTED" → "APPROVED — MANUAL POST PENDING" in mock mode) |
| v11b | 2026-04-07 | `openai_provider.py` | DraftWriter 프롬프트 오버라이드 (v10 → v11): SYSTEM_PROMPT 전면 교체 — hook 공식 5가지, DO NOT 목록 (AI 투성이 문구 / 번역 뉴스 톤), "why it matters" 지시, 한국 고유 용어 정의 지시, thread 억제 규칙 강화; user_msg에 "international audience, no prior Korea knowledge" 명시 |

---

## 이 문서의 목적

운영자 → Claude Code (또는 GPT) 전달 구조가 아래와 같다:
1. Claude Code가 작업하고 보고서 출력
2. 운영자가 보고서를 GPT에 복붙
3. GPT가 보고서를 보고 다음 프롬프트 작성
4. 운영자가 다시 Claude Code에 전달

이 문서는 Claude Code와 GPT 양쪽이 동시에 읽고 작업 기준을 잡을 수 있게 만들었다.

---

## 현재 코드베이스 실제 상태 (검토 완료 기준)

### 확인된 사실 (코드 직접 확인)

| 항목 | 상태 | 파일 |
|------|------|------|
| 파이프라인 뼈대 | ✅ 작동 | `orchestrator.py` |
| OpenAI 드래프트 | ✅ 연결됨 | `openai_provider.py` |
| Claude 리뷰어 | ✅ 연결됨 | `anthropic_provider.py` |
| Telegram 승인 루프 | ✅ 구현됨 | `telegram_bot.py` |
| X 게시 (Mock/Real) | ✅ 구현됨 | `x_publisher.py` |
| 중복 방지 | ✅ 구현됨 | `draft_service.py` |
| Rate Limiter | ✅ 구현됨 (하루 5/5/3) | `rate_limiter.py` |
| 테스트 76개 | ✅ 통과 | `tests/` |
| FastAPI admin | ✅ 구현됨 | `api/admin.py` |

### 현재 프롬프트 실제 품질 (솔직한 평가)

**OpenAI DraftWriter 프롬프트** (`openai_provider.py`):
- 문제: "write a FIRST DRAFT", "balanced" 지시만 있음
- 훅 공식 없음, 바이럴 각도 없음, 설명 대상(국제 독자) 고려 지시 약함
- 결과물: 평범한 뉴스 요약 수준 예상

**Anthropic Reviewer 프롬프트** (`anthropic_provider.py`):
- 문제: 리스크 분류는 있는데 품질 기준이 약함
- "sounds like AI?" 체크 없음
- "why this matters to international readers" 지시 없음

### 현재 하드코딩된 제한값

```python
# app/services/rate_limiter.py
DEFAULT_MAX_DRAFTS_PER_DAY = 5   # 하루 초안 5개
DEFAULT_MAX_TELEGRAM_PER_DAY = 5  # 하루 텔레그램 5개
DEFAULT_MAX_POSTS_PER_DAY = 3     # 하루 게시 3개
```

이 값은 `.env`로 외부화되어 있지 않다. 코드 직접 수정 필요.

---

## Claude Code에게 지금 당장 해야 할 작업

### TASK-01: rate_limiter 환경변수 외부화
**파일**: `app/services/rate_limiter.py`, `app/config.py`, `.env.example`

**이유**: 하루 3회 게시는 성장 불가. 운영자가 `.env`로 조절 가능하게 해야 함.
**COMMANDER_BRIEF 원칙**: Layer 1 수정. 작은 패치. 테스트 필수.

**정확한 작업 내용**:

1. `app/config.py`의 `Settings` 클래스에 아래 3개 필드 추가:
```python
max_drafts_per_day: int = Field(default=5, description="하루 최대 초안 생성 수")
max_telegram_per_day: int = Field(default=5, description="하루 최대 텔레그램 전송 수")
max_posts_per_day: int = Field(default=10, description="하루 최대 X 게시 수")
```
- `max_posts_per_day` 기본값은 **10**으로 설정 (기존 3에서 변경)

2. `app/services/rate_limiter.py`의 `__init__` 수정:
```python
def __init__(self, db: Session):
    self.db = db
    self.max_drafts = settings.max_drafts_per_day
    self.max_telegram = settings.max_telegram_per_day
    self.max_posts = settings.max_posts_per_day
```
- 기존 `max_drafts`, `max_telegram`, `max_posts` 파라미터 제거
- `settings`에서 직접 읽도록 변경
- 단, 테스트 호환성을 위해 `RateLimiter(db, max_drafts=X)` 형태도 유지 (override 가능하게)

3. `.env.example`에 추가:
```
MAX_DRAFTS_PER_DAY=5
MAX_TELEGRAM_PER_DAY=5
MAX_POSTS_PER_DAY=10
```

4. 작업 후 `pytest tests/test_rate_limiter.py -v` 실행. 기존 테스트 모두 통과해야 함.
5. 통과 안 되면 테스트 수정하지 말고 코드 수정.

---

### TASK-02: OpenAI DraftWriter 프롬프트 교체
**파일**: `app/providers/openai_provider.py`

**이유**: 현재 프롬프트는 평범한 요약 수준. 훅이 없으면 조회수가 없다.
**COMMANDER_BRIEF 원칙**: 텍스트 운영 시스템. credibility > virality.

**`SYSTEM_PROMPT` 전체 교체**:

```python
SYSTEM_PROMPT = """You are a first-draft writer for an English-language X (Twitter) account that explains Korean society, politics, policy, and economy to international audiences.

ACCOUNT IDENTITY:
- Target audience: Non-Koreans who are curious about Korea but don't follow Korean media
- Tone: Informed, clear, never sensational, never propaganda
- K-pop and Korean dramas are used ONLY as entry points — not as main content
- credibility > virality

YOUR JOB: Write a first draft only. A reviewer (Claude) will fact-check and refine after you.

HOOK FORMULA (use one of these patterns):
- "Korea just [did something notable for the first time / changed a major policy]:"
- "[Number] years ago, Korea [was X]. Now it's [Y]."
- "While [other countries] [do X], Korea [does Y]."
- "The [specific stat] about Korea that changes how you think about [broader topic]:"
- "What non-Koreans miss about Korea's [topic]:"

POST RULES:
1. Hook: One punchy line. Standalone. Must make you want to read more.
2. Body: Under 240 characters. One key insight. At least one specific number or fact.
3. Use plain English — if you use a Korean term (chaebol, jeonse, etc.), define it immediately.
4. Do NOT write like an AI — avoid: "it's worth noting", "it's important to", "furthermore", "as we can see", "delve into"
5. Do NOT sensationalize, do NOT editorialize politically

THREAD RULE: Only add thread_continuation if the topic genuinely requires more context. Not every post needs a thread.

Respond in JSON ONLY:
{
  "hook": "attention-grabbing first line (standalone)",
  "body": "main post body — under 240 chars, minimum one specific fact/number",
  "thread_continuation": "next tweet text if genuinely needed, or null",
  "category_suggestion": "politics|policy|economy|society|kpop_culture|evergreen",
  "tone_notes": "brief note on style choices made"
}"""
```

작업 후 `pytest tests/test_providers.py -v` 실행 확인.

---

### TASK-03: Anthropic Reviewer 프롬프트 강화
**파일**: `app/providers/anthropic_provider.py`

**이유**: 리뷰어가 품질 기준을 갖고 있지 않음. AI 냄새, 설명 부족, 국제 독자 고려 체크가 없음.
**COMMANDER_BRIEF 원칙**: 텍스트 품질 = 이 시스템의 핵심.

**`REVIEW_SYSTEM_PROMPT` 전체 교체**:

```python
REVIEW_SYSTEM_PROMPT = """You are the editorial reviewer and safety checker for an English-language X account about Korean affairs, written for international audiences.

ACCOUNT IDENTITY:
- Audience: Non-Koreans who don't follow Korean media
- Tone: Informed, clear, explanatory — not sensational, not propaganda
- credibility > virality

YOUR JOB:
1. Check if the draft is accurate (flag anything unconfirmed)
2. Check if a non-Korean can understand it without prior knowledge
3. Check if it sounds like a human wrote it (not AI)
4. Assess risk level
5. Refine the draft — keep body under 270 characters

QUALITY CHECKLIST (check all before responding):
- [ ] Does the hook make you want to read more? If not, rewrite it.
- [ ] Is there at least one specific number, stat, or concrete fact? If not, add or flag missing.
- [ ] Can a non-Korean understand this without googling? If not, add brief context.
- [ ] Does it sound like an AI wrote it? (check for: "it's worth noting", "furthermore", "as we can see", "delve", "tapestry") — if yes, rewrite those parts.
- [ ] Does it drift toward fandom tone, propaganda, or sensationalism? If yes, correct or reject.

RISK RULES:
- politics / policy / economy / society → medium or high (never low)
- kpop_culture with controversy → medium or high
- evergreen educational content with no controversy → can be low
- Unconfirmed rumors → always high, flag in risk_reasoning
- Sensational framing → always high

STRICT RULES:
- Never include unconfirmed information without flagging it
- Never sensationalize
- Keep body under 270 characters
- If the draft is unfixable (factually wrong, propaganda, or harmful), set recommended_action to "reject"

Respond in JSON ONLY:
{
  "hook": "final refined hook",
  "body": "final post body — under 270 chars",
  "thread_continuation": "optional or null",
  "category": "politics|policy|economy|society|kpop_culture|evergreen",
  "risk_level": "low|medium|high",
  "risk_reasoning": "specific reason for this risk level",
  "ai_rationale": "why this post serves international readers well",
  "recommended_action": "approve|review|reject",
  "quality_flags": {
    "hook_strength": "strong|weak|rewritten",
    "has_specific_fact": true,
    "international_context_clear": true,
    "sounds_human": true,
    "tone_clean": true
  }
}"""
```

**중요**: `ReviewResult` 데이터클래스(`app/providers/base.py`)에 `quality_flags` 필드가 없다.
두 가지 옵션:
- 옵션 A (권장): `ReviewResult`에 `quality_flags: dict = field(default_factory=dict)` 추가
- 옵션 B: Reviewer가 quality_flags를 생성하되 `ai_rationale` 문자열에 포함시켜 DB에 저장

**옵션 A로 진행할 것.** `base.py`에 필드 추가 후 `anthropic_provider.py`에서 파싱.

작업 후 `pytest tests/ -v` 전체 실행.

---

### TASK-04: topic_memory.py 스텁 추가 (Layer 2)
**새 파일**: `app/services/topic_memory.py`

**이유**: 반복 토픽 방지는 콘텐츠 신뢰도에 직결됨. 지금은 스텁만.
**COMMANDER_BRIEF 원칙**: Layer 2 — Layer 1 실패해도 무관.

```python
"""
토픽 메모리 서비스 (Layer 2 - Advisory)
========================================
최근 게시된 토픽을 기억해서 반복 게시를 방지합니다.

현재: 스텁 구현 (실제 분석 없음)
나중에: DB에서 최근 draft의 category + keyword 추출 + 유사도 체크

Layer 2 원칙: 이 서비스가 실패해도 Layer 1 파이프라인에 영향 없어야 함.
"""
import logging
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session
from app.models.content import Draft, ApprovalStatus

logger = logging.getLogger(__name__)


class TopicMemory:
    """최근 게시 토픽 기억 서비스 (Layer 2)"""

    def __init__(self, db: Session):
        self.db = db

    def get_recent_categories(self, days: int = 7) -> dict[str, int]:
        """
        최근 N일간 카테고리별 게시 횟수를 반환합니다.
        실패해도 빈 dict 반환 (Layer 1 영향 없음).
        """
        try:
            since = datetime.now(timezone.utc) - timedelta(days=days)
            drafts = (
                self.db.query(Draft)
                .filter(
                    Draft.published_at >= since,
                    Draft.approval_status == ApprovalStatus.PUBLISHED,
                )
                .all()
            )
            result: dict[str, int] = {}
            for d in drafts:
                cat = d.category.value
                result[cat] = result.get(cat, 0) + 1
            return result
        except Exception as e:
            logger.warning(f"[TopicMemory] get_recent_categories 실패 (무시): {e}")
            return {}

    def get_warning(self, category: str, days: int = 3, threshold: int = 3) -> str | None:
        """
        특정 카테고리가 최근 N일간 threshold 이상 게시됐으면 경고를 반환합니다.
        실패해도 None 반환 (Layer 1 영향 없음).

        Returns:
            경고 문자열 또는 None
        """
        try:
            counts = self.get_recent_categories(days=days)
            count = counts.get(category, 0)
            if count >= threshold:
                return (
                    f"[TopicMemory] '{category}' 최근 {days}일간 {count}회 게시됨. "
                    f"다른 카테고리 고려 권장."
                )
            return None
        except Exception as e:
            logger.warning(f"[TopicMemory] get_warning 실패 (무시): {e}")
            return None
```

이 파일은 현재 어디서도 호출하지 않아도 됨.
나중에 `orchestrator.py`에서 advisory 메시지로 연결할 예정.
테스트는 작성하지 않아도 됨 (스텁이므로).

---

### TASK-05: voice_guard.py 스텁 추가 (Layer 2)
**새 파일**: `app/services/voice_guard.py`

```python
"""
보이스 가드 서비스 (Layer 2 - Advisory)
========================================
AI 냄새 나는 표현, 팬덤 드리프트, propaganda 톤을 감지합니다.
현재: 단순 키워드 매칭 (스텁)
나중에: 더 정교한 텍스트 분석

Layer 2 원칙: 실패해도 Layer 1 파이프라인에 영향 없어야 함.
"""
import logging

logger = logging.getLogger(__name__)

# AI가 자주 쓰는 표현 (X에서 신뢰도 하락)
AI_PHRASES = [
    "it's worth noting",
    "it's important to",
    "as we can see",
    "in conclusion",
    "furthermore",
    "it is crucial",
    "delve into",
    "tapestry",
    "nuanced",
    "multifaceted",
    "at the end of the day",
    "game-changer",
    "paradigm shift",
]

# 팬덤 드리프트 신호
FANDOM_SIGNALS = [
    "stan", "iconic", "slay", "king", "queen",
    "serving", "ate", "no notes", "yasss", "omg",
    "periodt", "bestie",
]

# Propaganda / 선동 신호
PROPAGANDA_SIGNALS = [
    "enemies of", "destroy", "crushing", "regime",
    "propaganda", "wake up", "they don't want you to know",
]


class VoiceGuard:
    """보이스 가드 (Layer 2)"""

    def check(self, text: str) -> dict:
        """
        텍스트에서 문제 표현을 감지합니다.
        실패해도 빈 결과 반환.

        Returns:
            {
                "ai_phrases": [...],
                "fandom_signals": [...],
                "propaganda_signals": [...],
                "warning": "경고 메시지 또는 None"
            }
        """
        try:
            text_lower = text.lower()
            found_ai = [p for p in AI_PHRASES if p in text_lower]
            found_fandom = [p for p in FANDOM_SIGNALS if p in text_lower]
            found_propaganda = [p for p in PROPAGANDA_SIGNALS if p in text_lower]

            issues = []
            if found_ai:
                issues.append(f"AI 표현 감지: {found_ai}")
            if found_fandom:
                issues.append(f"팬덤 톤 감지: {found_fandom}")
            if found_propaganda:
                issues.append(f"선동 톤 감지: {found_propaganda}")

            return {
                "ai_phrases": found_ai,
                "fandom_signals": found_fandom,
                "propaganda_signals": found_propaganda,
                "warning": " | ".join(issues) if issues else None,
            }
        except Exception as e:
            logger.warning(f"[VoiceGuard] check 실패 (무시): {e}")
            return {
                "ai_phrases": [],
                "fandom_signals": [],
                "propaganda_signals": [],
                "warning": None,
            }
```

---

## Claude Code 작업 순서

```
TASK-01 → pytest tests/test_rate_limiter.py -v → 통과 확인
TASK-02 → pytest tests/test_providers.py -v → 통과 확인
TASK-03 → pytest tests/ -v → 전체 통과 확인
TASK-04 → 파일 생성 (테스트 불필요)
TASK-05 → 파일 생성 (테스트 불필요)
마지막 → pytest tests/ -v → 최종 전체 통과 확인 후 보고
```

---

## Claude Code 보고서 형식 (GPT에게 넘길 때 이 형식 유지)

작업 완료 후 아래 형식으로 보고서를 출력해라.
GPT가 이 보고서를 받아서 다음 프롬프트를 짜는 구조다.

```
### 작업 완료 보고서

**완료된 TASK**: TASK-01, TASK-02, ...
**실패/스킵된 TASK**: (있으면 이유와 함께)

**변경된 파일**:
- app/config.py: [어떤 변경]
- app/providers/openai_provider.py: [어떤 변경]
- ...

**테스트 결과**:
- 전체: X passed, Y failed
- 실패 있으면: [파일명::테스트명] — [오류 요약]

**현재 시스템 상태**:
- Layer 1 정상 작동: YES/NO
- Mock 모드 유지: YES/NO
- rate limit 설정: drafts=X, telegram=Y, posts=Z

**다음 권장 작업** (GPT가 프롬프트 짤 때 참고):
- [다음에 해야 할 것]
- [막힌 것 있으면 설명]
```

---

## GPT가 프롬프트 짤 때 주의사항

운영자가 Claude Code 보고서를 GPT에 복붙할 것이다.
GPT는 아래를 반드시 지킬 것:

1. **COMMANDER_BRIEF.md 원칙을 먼저 확인해라** — 이미지 생성, 자동 게시, 구조 재설계 제안 금지
2. **Layer 1을 건드리는 제안은 테스트 계획과 함께** — "이렇게 바꿔라" 만 하지 말고 "어떤 테스트로 확인할지"까지
3. **Claude Code 보고서의 실패/스킵 항목부터 먼저 처리** — 새 기능보다 미완성 작업 먼저
4. **지시문은 파일명 + 함수명 + 정확한 변경 내용** — "프롬프트를 개선해라" 같은 추상 지시 금지
5. **작업 단위는 하나씩** — 한 번에 5개 파일 동시 수정 지시하지 말 것

---

## 현재 이 시스템의 실제 병목 (냉정한 진단)

코드 전체를 읽었다. 병목은 두 가지다.

**병목 1: 프롬프트 품질** (TASK-02, TASK-03으로 해결)
현재 프롬프트로는 X에서 주목받는 포스트가 나오지 않는다.
훅 공식, 설명형 문장 지시, AI 표현 금지가 없다.

**병목 2: 실제 API 키 연결 여부** (코드로 해결 불가, 운영자 직접)
Mock 모드로는 실제 성장 여부를 알 수 없다.
TASK-01~05 완료 후 운영자가 `.env`에 실제 키 넣고 테스트해야 한다.

코드 구조 자체는 탄탄하다. 지금 당장 재설계할 이유 없다.
