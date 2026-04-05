# GROWTH_ROADMAP.md
# X 팔로워 100만 목표 - Claude Code 작업 지시서
# 작성자: Perplexity Computer (운영자 승인형 인프라 분석)
# 기준일: 2026-04-05
# 대상: kluck77/x-posting-system

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
- **이미지 없음**: 텍스트 전용 = 낮은 도달
- **포스팅 횟수 너무 적음**: 하루 3회는 성장 불가

---

## 우선순위 작업 목록 (ROI 높은 순)

### 🔴 PRIORITY 1 - 지금 바로 구현 (이것 없으면 성장 0)

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

**이유**: 하루 3회로는 알고리즘이 계정을 무시한다. X 성장 사례 분석 결과 최소 8-12회/일이 필요.

---

#### P1-B: 콘텐츠 전략 파일 추가
**새 파일**: `app/content_strategy.py`

```python
# 이 파일이 없으면 AI가 뭘 써야 할지 모른다
# 100만 팔로워 계정은 반드시 명확한 콘텐츠 포뮬러가 있다

CONTENT_PILLARS = {
    "korea_vs_world": {  # 비교 콘텐츠 - 가장 공유 잘 됨
        "ratio": 0.30,
        "examples": [
            "Korea's birth rate vs Japan vs Germany",
            "Korean work hours vs OECD average",
        ]
    },
    "surprising_facts": {  # 놀라운 사실 - 바이럴 확률 높음
        "ratio": 0.25,
        "examples": [
            "Things non-Koreans don't know about Korea",
            "Korean statistics that will shock you",
        ]
    },
    "explainer": {  # 설명 콘텐츠 - 저장/공유율 높음
        "ratio": 0.25,
        "examples": [
            "Why Korea's education system works (and doesn't)",
            "How Korean conglomerates (chaebols) actually work",
        ]
    },
    "news_context": {  # 뉴스 + 맥락 - 시의성
        "ratio": 0.20,
        "examples": [
            "What today's Korea news actually means",
        ]
    }
}

BEST_POST_TIMES_KST = [
    "07:00",  # 한국 출근 전 / 미국 저녁
    "12:00",  # 점심
    "19:00",  # 퇴근
    "22:00",  # 취침 전 / 미국 아침
]

HOOK_TEMPLATES = [
    "Korea just did something no other country has done:",
    "What happens when you combine {A} with {B}? Korea found out.",
    "{Number} things about Korea that non-Koreans find shocking:",
    "The real reason Korea {phenomenon}:",
    "Korea's {topic} is unlike anything in the world. Here's why:",
]
```

**작업 내용**:
- 위 파일 생성
- `app/orchestrator.py`에서 `generate_draft` 호출 시 `content_pillar`를 AI 프롬프트에 포함
- `anthropic_provider.py`와 `openai_provider.py`의 SYSTEM_PROMPT에 콘텐츠 전략 주입

---

#### P1-C: OpenAI 프롬프트 대폭 강화
**파일**: `app/providers/openai_provider.py`

현재 SYSTEM_PROMPT 문제점:
- 훅 공식이 없다
- 어떤 포맷이 X에서 잘 먹히는지 모른다
- 바이럴 요소가 없다

**교체할 SYSTEM_PROMPT**:
```python
SYSTEM_PROMPT = """You are a top 0.1% X (Twitter) content strategist specializing in Korean affairs for international audiences.

Your posts have driven millions of engagements. You know exactly what makes people stop scrolling.

VIRAL FORMULA (follow this strictly):
1. Hook: Open with a jaw-dropping fact, counterintuitive insight, or strong contrast. First 5 words must stop the scroll.
2. Body: One clear, specific insight. Concrete numbers beat vague claims. Under 240 chars.
3. CTA: End with a question or "Thread below 🧵" to drive engagement.

PROVEN HOOK PATTERNS:
- "Korea just became the first country to..."
- "{Number} years ago Korea was... Now it's..."
- "While the West debates X, Korea already..."
- "Korea's {topic}: the stat that will change how you think about {broader topic}"

CONTENT RULES:
- Always give non-Koreans context they need
- Use specific numbers (not "many" or "some")
- Compare to other countries when possible (makes it shareable)
- Avoid jargon — if you use a Korean term, explain it immediately
- No sensationalism, but don't be boring either

POST STRUCTURE:
- Hook line (standalone punch)
- 1-2 context sentences
- The key insight or fact
- Closing question or hook for more

Respond in JSON ONLY:
{
  "hook": "first line — must stop scrolling",
  "body": "full post text under 240 chars (not counting hook)",
  "thread_continuation": "next tweet if this needs more context, or null",
  "category_suggestion": "politics|policy|economy|society|kpop_culture|evergreen",
  "virality_angle": "what makes this shareable",
  "tone_notes": "style notes"
}"""
```

---

#### P1-D: Anthropic Reviewer 프롬프트 강화
**파일**: `app/providers/anthropic_provider.py`

**추가할 평가 기준**:
```python
REVIEW_SYSTEM_PROMPT에 아래 추가:

VIRALITY CHECKLIST (score each 1-5, include in response):
- scroll_stop_score: Does the hook make you stop scrolling?
- shareability_score: Would a non-Korean share this to explain Korea to friends?
- clarity_score: Can someone with zero Korea knowledge understand this?
- factual_density: Does it have at least one specific number/stat?

If any score is below 3, rewrite that element.

JSON에 추가:
"virality_scores": {
  "scroll_stop": 1-5,
  "shareability": 1-5,
  "clarity": 1-5,
  "factual_density": 1-5
},
"improvement_notes": "what was changed and why"
```

---

### 🟡 PRIORITY 2 - 스텁 세팅 (구조만 만들고 나중에 채움)

#### P2-A: RSS 소스 자동 수집 스텁
**새 파일**: `app/services/rss_collector.py`

```python
"""
RSS 자동 수집 서비스 (스텁)
현재: 구조만 정의, 실제 수집은 수동
나중에: 주기적 자동 수집으로 업그레이드

대상 소스 (검증 필요):
- Korea JoongAng Daily RSS
- The Korea Herald RSS  
- Yonhap News English RSS
- Korea Times RSS
"""

class RSSCollector:
    SOURCES = [
        "https://koreajoongangdaily.joins.com/rss/news",
        "http://www.koreaherald.com/rss/all.xml",
        "https://en.yna.co.kr/RSS/news.xml",
    ]
    
    def collect(self) -> list[dict]:
        # TODO: 구현 예정
        # 지금은 빈 리스트 반환
        return []
    
    def filter_by_relevance(self, items: list[dict]) -> list[dict]:
        # TODO: 구현 예정
        return items
```

**왜 스텁만**: RSS 수집은 소스 안정성 검증이 필요. 잘못된 소스에서 자동 수집하면 품질 하락.

---

#### P2-B: 스레드 게시 스텁
**파일**: `app/services/x_publisher.py`

```python
# publish() 메서드에 thread_continuation 처리 추가

async def publish_thread(self, draft: Draft) -> PublishResult:
    """
    스레드 게시 (스텁)
    현재: 단일 트윗만 게시
    나중에: thread_continuation이 있으면 스레드로 게시
    """
    # Step 1: 첫 트윗 게시
    first_result = await self.publish(draft)
    if not first_result.success:
        return first_result
    
    # Step 2: 스레드 연속 (스텁)
    if draft.thread_continuation:
        # TODO: in_reply_to_tweet_id 파라미터로 첫 트윗에 답글
        pass
    
    return first_result
```

---

#### P2-C: 성과 추적 스텁
**새 파일**: `app/services/analytics_service.py`

```python
"""
성과 추적 서비스 (스텁)
X API v2로 각 게시물의 조회수/좋아요/리트윗 추적
나중에: 어떤 콘텐츠 타입이 성장에 기여하는지 분석
"""

class AnalyticsService:
    def get_tweet_metrics(self, tweet_id: str) -> dict:
        # TODO: X API v2 GET /2/tweets/:id?tweet.fields=public_metrics
        return {
            "impressions": 0,
            "likes": 0, 
            "retweets": 0,
            "replies": 0,
        }
    
    def get_best_performing_category(self) -> str:
        # TODO: DB에서 성과 높은 카테고리 분석
        return "unknown"
```

---

### 🟢 PRIORITY 3 - 나중에 구현

#### P3-A: 스케줄러 (게시 시간 자동화)
- 지금은 수동 /ingest → 텔레그램 승인 → 게시
- 나중에: 매일 특정 시간대에 자동으로 큐에서 꺼내 게시
- **주의**: 완전 자동 게시는 절대 금지. 승인 후 큐에 넣고, 시간만 자동화

#### P3-B: 이미지 자동 생성
- DALL-E 또는 Stable Diffusion으로 포스트용 카드 이미지
- 텍스트 전용 대비 인게이지먼트 2-3배 차이
- 먼저 텍스트 품질 안정화 후 추가

#### P3-C: Gemini 리서치 연동
- 현재 Researcher 역할이 Mock
- Gemini로 배경 리서치 자동화
- 팩트 밀도 높아지면 공유율 상승

---

### 🔒 지금은 금지

- `ENABLE_AUTO_POST_LOW_RISK=true` 설정 변경
- 자동 팔로우/언팔로우 기능
- 댓글/DM 자동화
- 여러 계정 동시 운영
- 게시 후 자동 삭제/수정

---

## 즉시 실행 가능한 운영 전략 (코드 수정 없이)

### 콘텐츠 입력 공식
매일 이 형식으로 /ingest에 입력:

```
타입 1 (비교): "Korea's [지표] vs [다른나라] - 최신 데이터"
타입 2 (팩트): "[숫자]년 만에 처음인 [한국 현상]"  
타입 3 (설명): "비한국인이 모르는 [한국 시스템] 작동 방식"
```

### 소스 우선순위 (지금 수동으로 쓸 것)
1. 통계청 영문 보도자료
2. 한국은행 영문 보고서
3. Korea JoongAng Daily
4. Our World in Data (한국 데이터)

---

## 클로드 코드 실행 순서

```
1단계: P1-A 먼저 (rate_limiter 한도 현실화)
2단계: P1-C + P1-D (프롬프트 교체 - 가장 즉각적인 품질 향상)
3단계: P1-B (content_strategy.py 파일 생성)
4단계: 실제 API 키로 10개 포스트 생성 → 텔레그램 승인 테스트
5단계: P2 스텁들 추가
```

---

## 현재 시스템에서 팔로워 100만까지의 현실적 경로

| 단계 | 팔로워 | 필요한 것 | 예상 기간 |
|------|--------|-----------|-----------|
| 지금 | 0 | API 키 연결, 하루 10회 게시 시작 | 즉시 |
| Phase 1 | 0 → 1,000 | 고품질 훅, 일관성, 하루 10회 | 2-3개월 |
| Phase 2 | 1,000 → 10,000 | 바이럴 1-2개, 스레드 추가 | 3-6개월 |
| Phase 3 | 10,000 → 100,000 | 이미지, 협업, 뉴스 선점 | 6-18개월 |
| Phase 4 | 100,000 → 1,000,000 | 미디어 언급, 유명인 RT | 1-3년 |

**가장 현실적인 병목**: 콘텐츠 품질과 훅의 힘. 시스템이 아니라 콘텐츠가 팔로워를 만든다.

---

## 이 파일의 용도

이 파일은 Claude Code가 다음 작업 시 참조하는 지시서입니다.
- 작업 순서를 바꾸지 마세요
- P1을 모두 완료하기 전에 P2로 넘어가지 마세요
- "지금은 금지" 항목은 운영자가 명시적으로 승인하기 전까지 구현하지 마세요
- 각 P1 작업 완료 후 `pytest tests/ -v` 실행하여 기존 76개 테스트 통과 확인

