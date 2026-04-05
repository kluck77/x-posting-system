# GROWTH_ROADMAP.md
# X 팔로워 100만 목표 - Claude Code 작업 지시서
# 작성자: Perplexity Computer
# 업데이트: 2026-04-05 (COMMANDER_BRIEF 반영)
# 대상: kluck77/x-posting-system

> **이 문서는 COMMANDER_BRIEF.md의 원칙 하에 작동한다.**
> 충돌 시 COMMANDER_BRIEF.md가 우선한다.

---

## 현재 시스템 진단 (솔직한 평가)

### 잘 된 것
- 승인 없이 게시 불가 구조 ✅
- Mock 모드로 전체 파이프라인 테스트 가능 ✅
- 76개 테스트 통과 ✅
- 중복 방지 로직 ✅
- SQLite 감사 로그 ✅

### 팔로워 100만 관점에서 치명적으로 빠진 것
- **콘텐츠 전략 없음**: 뭘 올릴지 기준이 없다
- **스케줄 없음**: 언제 올릴지 자동화 없다
- **RSS/소스 자동 수집 없음**: 수동 입력만 가능
- **스레드 게시 없음**: 단일 트윗만 지원
- **성과 추적 없음**: 조회수/팔로워 변화 모름
- **포스팅 횟수 너무 적음**: 하루 3회는 성장 불가
- **댓글/인용RT 초안 없음**: 메인 포스트만 생성

---

## 우선순위 작업 목록 (ROI 높은 순)

### 🔴 PRIORITY 1 - 지금 바로 구현

#### P1-A: 일일 게시 한도 현실화
**파일**: `app/config.py`, `app/services/rate_limiter.py`

```
현재: X 게시 하루 3회
목표: 하루 10-15회 (팔로워 성장 최소 조건)
```

**작업 내용**:
- `rate_limiter.py`의 `DEFAULT_MAX_POSTS_PER_DAY = 3` → `10`으로 변경
- `DEFAULT_MAX_DRAFTS_PER_DAY = 5` → `15`으로 변경
- `DEFAULT_MAX_TELEGRAM_PER_DAY = 5` → `15`으로 변경
- `.env.example`에 `MAX_POSTS_PER_DAY`, `MAX_DRAFTS_PER_DAY` 환경변수 추가
- `config.py`에 해당 환경변수 필드 추가

**이유**: 하루 3회로는 알고리즘이 계정을 무시한다. 최소 8-12회/일이 필요.

---

#### P1-B: 콘텐츠 전략 파일 추가
**새 파일**: `app/content_strategy.py`

Layer 2 성격. Layer 1에 영향 없게 얇게 설계할 것.

```python
# 이 파일은 advisory 전용이다. 실제 게시 흐름을 막으면 안 된다.

CONTENT_PILLARS = {
    "korea_vs_world": {
        "ratio": 0.30,
        "description": "비교 콘텐츠 - 가장 공유 잘 됨"
    },
    "surprising_facts": {
        "ratio": 0.25,
        "description": "놀라운 사실 - 바이럴 확률 높음"
    },
    "explainer": {
        "ratio": 0.25,
        "description": "설명 콘텐츠 - 저장/공유율 높음"
    },
    "news_context": {
        "ratio": 0.20,
        "description": "뉴스 + 맥락 - 시의성"
    }
}

HOOK_TEMPLATES = [
    "Korea just did something no other country has done:",
    "{Number} things about Korea that non-Koreans find shocking:",
    "The real reason Korea {phenomenon}:",
    "Korea's {topic} is unlike anything in the world. Here's why:",
]
```

이 파일은 DraftWriter 프롬프트에 참고용으로만 주입한다.
이 파일이 없어도 파이프라인은 돌아가야 한다.

---

#### P1-C: OpenAI 프롬프트 강화
**파일**: `app/providers/openai_provider.py`

현재 SYSTEM_PROMPT 문제점:
- 훅 공식이 없다
- 바이럴 요소가 없다
- 설명형 문장 지침이 약하다

**교체할 SYSTEM_PROMPT**:
```python
SYSTEM_PROMPT = """You are a top-tier X (Twitter) content writer specializing in Korean affairs for international audiences.

Your job is to write FIRST DRAFTS. A reviewer will check and refine after you.

CONTENT PHILOSOPHY:
- credibility > virality
- Explain Korea to people who know nothing about it
- Use specific numbers, not vague claims
- Compare to other countries when it adds clarity
- Avoid AI-sounding phrases and filler sentences

HOOK FORMULA (proven patterns):
- "Korea just became the first country to..."
- "[Number] years ago Korea was X. Now it's Y."
- "While the West debates X, Korea already..."
- "The stat about Korea that changes how you think about [broader topic]:"

POST STRUCTURE:
1. Hook line (standalone, stops scrolling)
2. 1-2 context sentences (what non-Koreans need to know)
3. The key insight or fact (specific number preferred)
4. Closing: question or thread hook

STRICT RULES:
- Main post body under 240 characters (not counting hook)
- No sensationalism
- No propaganda tone
- No fandom-style language
- If you use a Korean term, explain it immediately

Respond in JSON ONLY:
{
  "hook": "first line — must stop scrolling",
  "body": "full post text under 240 chars",
  "thread_continuation": "next tweet if needed, or null",
  "category_suggestion": "politics|policy|economy|society|kpop_culture|evergreen",
  "tone_notes": "style notes"
}"""
```

---

#### P1-D: Anthropic Reviewer 프롬프트 강화
**파일**: `app/providers/anthropic_provider.py`

REVIEW_SYSTEM_PROMPT에 아래 평가 기준 추가:

```
QUALITY CHECKLIST (include in response):
- Does the hook make you stop scrolling? (yes/no + reason)
- Would a non-Korean share this to explain Korea to friends? (yes/no)
- Does it have at least one specific number or stat? (yes/no)
- Does it sound like AI wrote it? (yes/no — if yes, rewrite)
- Does it drift toward fandom or propaganda tone? (yes/no — if yes, reject)

JSON에 추가:
"quality_flags": {
  "scroll_stop": true/false,
  "shareable": true/false,
  "has_specific_fact": true/false,
  "sounds_like_ai": true/false,
  "tone_drift": true/false
},
"improvement_notes": "what was changed and why"
```

---

#### P1-E: 댓글 / 인용RT 초안 생성 추가
**COMMANDER_BRIEF 섹션 1 요구사항**

현재 시스템은 메인 포스트만 생성한다.
댓글 초안과 인용RT 초안도 생성해야 한다.

**작업 내용**:
- `app/models/content.py`에 `DraftType` enum 추가
  ```python
  class DraftType(str, enum.Enum):
      MAIN_POST = "main_post"
      REPLY = "reply"
      QUOTE_RT = "quote_rt"
      THREAD = "thread"
  ```
- `Draft` 모델에 `draft_type` 필드 추가 (기본값: `main_post`)
- `draft_type` 필드가 없어도 기존 코드가 작동하게 default 설정
- Orchestrator에 `generate_reply_draft()`, `generate_quote_draft()` 메서드 추가 (스텁도 무방)
- Telegram 승인 카드에 draft_type 표시 추가

---

### 🟡 PRIORITY 2 - 스텁 세팅 (구조만, 나중에 채움)

#### P2-A: topic_memory.py (COMMANDER_BRIEF 섹션 5 #1)
**새 파일**: `app/services/topic_memory.py`

```python
"""
토픽 메모리 서비스 (Layer 2)
이 서비스가 실패해도 Layer 1은 정상 작동해야 함.
최근 게시된 토픽을 기억해서 반복 방지.

현재: 스텁만 구현
나중에: 실제 토픽 추출 + 중복 경고
"""

class TopicMemory:
    def get_recent_topics(self, days: int = 7) -> list[str]:
        # TODO: DB에서 최근 게시된 draft의 category + keywords 추출
        return []
    
    def is_topic_repeated(self, topic: str, days: int = 3) -> bool:
        # TODO: 최근 N일 내 같은 토픽이 게시됐는지 확인
        return False
    
    def get_topic_warning(self, topic: str) -> str | None:
        # TODO: 반복 토픽이면 경고 메시지 반환
        return None
```

---

#### P2-B: voice_guard.py (COMMANDER_BRIEF 섹션 5 #2)
**새 파일**: `app/services/voice_guard.py`

```python
"""
보이스 가드 서비스 (Layer 2)
이 서비스가 실패해도 Layer 1은 정상 작동해야 함.
AI 같은 표현, 팬덤 드리프트, propaganda 톤 감지.

현재: 스텁만 구현
나중에: 실제 텍스트 분석
"""

AI_SOUNDING_PHRASES = [
    "it's worth noting",
    "it's important to",
    "as we can see",
    "in conclusion",
    "furthermore",
    "it is crucial",
    "delve into",
    "tapestry",
]

FANDOM_DRIFT_SIGNALS = [
    "stan", "iconic", "slay", "king", "queen",
    "serving", "ate", "no notes",
]

class VoiceGuard:
    def check_draft(self, text: str) -> dict:
        # TODO: 실제 분석 구현
        return {
            "ai_phrases_found": [],
            "fandom_signals_found": [],
            "warning": None,
        }
```

---

#### P2-C: RSS 소스 자동 수집 스텁
**새 파일**: `app/services/rss_collector.py`

```python
"""
RSS 자동 수집 서비스 (스텁)
현재: 구조만 정의, 실제 수집은 수동
나중에: 주기적 자동 수집으로 업그레이드

대상 소스 (안정성 검증 필요):
- Korea JoongAng Daily
- The Korea Herald
- Yonhap News English
"""

class RSSCollector:
    SOURCES: list[str] = []  # TODO: 검증된 RSS URL 추가
    
    def collect(self) -> list[dict]:
        # TODO: 구현 예정
        return []
```

---

#### P2-D: 스레드 게시 스텁
**파일**: `app/services/x_publisher.py`

```python
# publish() 메서드에 thread_continuation 처리 추가 (스텁)
async def publish_thread(self, draft: Draft) -> PublishResult:
    """
    스레드 게시 (스텁)
    현재: 단일 트윗만 게시
    나중에: thread_continuation 있으면 스레드로 게시
    """
    first_result = await self.publish(draft)
    if not first_result.success:
        return first_result
    
    if draft.thread_continuation:
        # TODO: X API v2 in_reply_to_tweet_id 파라미터 사용
        pass
    
    return first_result
```

---

### 🟢 PRIORITY 3 - 나중에 구현

- 스케줄러: 게시 시간 자동화 (승인 후 큐에서 꺼내는 것만, 승인은 여전히 수동)
- weekly content mix advisory report
- quality gate advisory (게시 막는 게 아니라 경고만)
- performance suggestions (X API로 조회수 추적)

---

### 🔒 영구 금지 (COMMANDER_BRIEF 섹션 2, 3)

- DALL-E / Stable Diffusion / 이미지 생성 계열 전부
- 자동 좋아요 / 자동 팔로우 / 자동 리플
- 승인 없는 자동 게시
- 구조 전면 재설계
- dashboard 대형화
- multi-account 지원

---

## 클로드 코드 실행 순서

```
1단계: P1-A (rate_limiter 한도 현실화) → pytest 확인
2단계: P1-C + P1-D (프롬프트 교체) → pytest 확인
3단계: P1-B (content_strategy.py) → pytest 확인
4단계: P1-E (DraftType 추가, 댓글/인용RT 스텁) → pytest 확인
5단계: P2 스텁들 추가 → pytest 확인
6단계: 실제 API 키로 end-to-end 테스트
```

**각 단계마다 `pytest tests/ -v` 실행 필수. 기존 76개 테스트 모두 통과해야 다음 단계.**

---

## 현실적 경로

| 단계 | 팔로워 | 핵심 조건 |
|------|--------|-----------|
| 지금 | 0 | API 키 연결, 하루 10회 게시 시작 |
| Phase 1 | → 1,000 | 일관성 + 훅 품질 + 하루 10회 |
| Phase 2 | → 10,000 | 스레드 추가 + 댓글 참여 |
| Phase 3 | → 100,000 | topic memory + voice consistency |
| Phase 4 | → 1,000,000 | 미디어 언급, 자연 바이럴 |

**가장 현실적인 병목: 콘텐츠 품질과 훅의 힘. 시스템이 아니라 콘텐츠가 팔로워를 만든다.**
