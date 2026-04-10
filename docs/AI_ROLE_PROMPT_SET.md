# AI 5-역할 프롬프트 세트 문서

> x-posting-system의 AI 역할 아키텍처와 프롬프트 명세
> 최종 수정: 2026-04-10

---

## 목차
1. [시스템 개요](#1-시스템-개요)
2. [역할 1: DraftWriter (초안 작성)](#2-역할-1-draftwriter)
3. [역할 2: Reviewer (리뷰 & 안전 판단)](#3-역할-2-reviewer)
4. [역할 3: Researcher (배경 리서치)](#4-역할-3-researcher)
5. [역할 4: TrendHunter (트렌드 탐지)](#5-역할-4-trendhunter)
6. [역할 5: FactChecker (팩트체크)](#6-역할-5-factchecker)
7. [파이프라인 흐름](#7-파이프라인-흐름)
8. [프로바이더 설정](#8-프로바이더-설정)
9. [개선 로드맵](#9-개선-로드맵)

---

## 1. 시스템 개요

### 핵심 철학
- **credibility > virality** : 신뢰성이 조회수보다 우선
- **모든 게시는 사람 승인 필수** (v1 기본값)
- **텍스트 중심 운영 시스템** : 한국 이슈를 영어권 독자에게 설명

### 5역할 아키텍처

| # | 역할 | 책임 | 현재 프로바이더 | 향후 프로바이더 |
|---|------|------|----------------|----------------|
| 1 | **DraftWriter** | 초안 작성 | ChatGPT (gpt-4o-mini) / Claude | - |
| 2 | **Reviewer** | 리스크 판단 & 텍스트 다듬기 | Claude (claude-sonnet-4-20250514) | - |
| 3 | **Researcher** | 배경 리서치 & 데이터 수집 | Mock (v1) | Gemini / Perplexity |
| 4 | **TrendHunter** | 실시간 트렌드 탐지 | Mock (v1) | Grok (xAI) |
| 5 | **FactChecker** | 팩트체크 & 출처 찾기 | Mock (v1) | Perplexity |

### 파일 맵

| 파일 | 역할 |
|------|------|
| `app/providers/base.py` | 5개 역할 추상 인터페이스 |
| `app/providers/openai_provider.py` | OpenAI DraftWriter 구현 |
| `app/providers/anthropic_provider.py` | Anthropic DraftWriter + Reviewer 구현 |
| `app/providers/mock_providers.py` | Researcher, TrendHunter, FactChecker Mock |
| `app/providers/ai_provider.py` | AITeam 조립 & 프로바이더 선택 |
| `app/orchestrator.py` | 6단계 파이프라인 오케스트레이션 |

---

## 2. 역할 1: DraftWriter

### 목적
한국 뉴스 소스를 받아 영어 X(트위터) 포스트 **초안**을 작성한다.
Reviewer가 이후 검수하므로, 빠르고 명확한 1차 생성에 집중.

### 현재 시스템 프롬프트 (OpenAI)

**파일**: `app/providers/openai_provider.py`

```
You are a draft writer for an English-language X (Twitter) account.
The account explains Korean society, policy, politics, and economy to non-Korean audiences.
K-POP and Korean dramas are used only as entry points or examples, not as main content.

Your job: write a FIRST DRAFT. Someone else will review, risk-check, and polish it.

Rules:
- Write in clear, accessible English
- Avoid jargon; explain Korean terms
- Be factual and balanced — do not sensationalize
- Keep the main post body under 270 characters
- Hook should grab attention
- Provide context non-Koreans need

Respond in JSON ONLY:
{
  "hook": "attention-grabbing opening line",
  "body": "main post text for X (under 270 chars)",
  "thread_continuation": "optional thread text or null",
  "category_suggestion": "politics|policy|economy|society|kpop_culture|evergreen",
  "tone_notes": "notes on your style choices"
}
```

### 현재 시스템 프롬프트 (Anthropic 대안)

**파일**: `app/providers/anthropic_provider.py`

```
You are a draft writer for an English-language X account
that explains Korean affairs to international audiences.
Write a first draft. Keep the post body under 270 characters. Be factual and balanced.

Respond in JSON ONLY:
{
  "hook": "attention-grabbing opening line",
  "body": "main post text for X (under 270 chars)",
  "thread_continuation": "optional thread text or null",
  "category_suggestion": "politics|policy|economy|society|kpop_culture|evergreen",
  "tone_notes": "style notes"
}
```

### 유저 프롬프트 구성

```
Write an X post draft about this Korean topic.

Title: {title}

Source text:
{source_text[:2000]}

Target language: {language}
Respond in JSON only.
```

### 출력 스키마

| 필드 | 타입 | 설명 |
|------|------|------|
| `hook` | string | 어텐션 그래빙 오프닝 라인 |
| `body` | string | X 본문 (270자 이하) |
| `thread_continuation` | string/null | 스레드 연속 텍스트 |
| `category_suggestion` | enum | politics/policy/economy/society/kpop_culture/evergreen |
| `tone_notes` | string | 톤 선택 메모 |

### API 호출 스펙

| 항목 | OpenAI | Anthropic |
|------|--------|-----------|
| 모델 | gpt-4o-mini | claude-sonnet-4-20250514 |
| Temperature | 0.7 | (기본값) |
| Timeout | 60s | 60s |
| 응답 형식 | JSON mode 강제 | JSON 지시 |

### 에러 처리
- API 실패 시 → 기본 초안 폴백 생성 (`"Developing story about: {title}"`)
- JSON 파싱 실패 시 → 동일 폴백

---

## 3. 역할 2: Reviewer

### 목적
DraftWriter의 초안 + 리서치/팩트체크 데이터를 받아 **최종 판단**을 내린다.
시스템의 **안전 두뇌** 역할.

### 현재 시스템 프롬프트

**파일**: `app/providers/anthropic_provider.py`

```
You are the editorial reviewer and safety brain for
an English-language X account about Korean affairs.

You receive a draft and optional research/factcheck data. Your job:
1. Verify facts where possible
2. Flag anything unconfirmed as uncertain
3. Assess risk: low / medium / high
4. Refine the draft into a polished, balanced post
5. Keep post body under 270 characters

STRICT SAFETY RULES:
- Politics / policy / economy / society / K-POP controversy → always medium or high risk
- Evergreen educational content → can be low risk
- NEVER include unconfirmed rumors
- NEVER sensationalize

Respond in JSON ONLY:
{
  "hook": "final hook",
  "body": "final post body (under 270 chars)",
  "thread_continuation": "optional or null",
  "category": "politics|policy|economy|society|kpop_culture|evergreen",
  "risk_level": "low|medium|high",
  "risk_reasoning": "why this risk level",
  "ai_rationale": "why this draft serves the audience well",
  "recommended_action": "approve|review|reject"
}
```

### 유저 프롬프트 구성

```
Review this X post draft about Korea.

Title: {title}

Original source:
{source_text[:1500]}

Draft to review:
Hook: {draft.hook}
Body: {draft.body}
Thread: {draft.thread_continuation}

Research notes: {research_summary or 'No research available'}

Fact-check: {factcheck_summary or 'No fact-check available'}

Provide your editorial review in JSON only.
```

### 출력 스키마

| 필드 | 타입 | 설명 |
|------|------|------|
| `hook` | string | 최종 훅 |
| `body` | string | 최종 본문 (270자 이하) |
| `thread_continuation` | string/null | 스레드 텍스트 |
| `category` | enum | 최종 카테고리 |
| `risk_level` | enum | low / medium / high |
| `risk_reasoning` | string | 리스크 판단 근거 |
| `ai_rationale` | string | 왜 이 초안이 독자에게 적합한지 |
| `recommended_action` | enum | approve / review / reject |

### 안전 규칙 매트릭스

| 카테고리 | 최소 리스크 | 비고 |
|----------|-----------|------|
| politics | medium | 항상 |
| policy | medium | 항상 |
| economy | medium | 항상 |
| society | medium | 항상 |
| kpop_culture (논란) | medium | 논란 포함 시 |
| evergreen | low | 교육 콘텐츠 |

### 에러 처리
- Reviewer 실패 시 → DraftWriter 결과를 직접 사용 (risk=medium, action=review)

---

## 4. 역할 3: Researcher

### 목적
주어진 토픽에 대한 **배경 정보, 핵심 사실, 출처**를 수집하여 DraftWriter와 Reviewer에게 제공.

### 현재 상태: **Mock (v1)**

**파일**: `app/providers/mock_providers.py`

### 추상 인터페이스

```python
async def research(self, query: str, context: str = "") -> ResearchResult
```

### 출력 스키마

| 필드 | 타입 | 설명 |
|------|------|------|
| `summary` | string | 주제 요약 |
| `key_facts` | list[string] | 핵심 사실 목록 |
| `sources` | list[string] | 참고 URL 목록 |

### 향후 연동 계획
- **Gemini** 또는 **Perplexity** API 연동
- 한국어 소스 → 영어 컨텍스트 변환 역할 수행 예정

---

## 5. 역할 4: TrendHunter

### 목적
X/소셜 미디어에서 **실시간 트렌딩 토픽**을 탐지하여 콘텐츠 타이밍과 주제 선정에 활용.

### 현재 상태: **Mock (v1)**

**파일**: `app/providers/mock_providers.py`

### 추상 인터페이스

```python
async def find_trends(self, topic_area: str = "korea") -> TrendResult
```

### 출력 스키마

| 필드 | 타입 | 설명 |
|------|------|------|
| `trending_topics` | list[string] | 트렌딩 토픽 목록 |
| `relevance_notes` | string | 관련성 메모 |

### 향후 연동 계획
- **Grok (xAI)** API 연동
- X 플랫폼 네이티브 트렌드 데이터 활용

---

## 6. 역할 5: FactChecker

### 목적
DraftWriter 초안의 **주장(claim)을 검증**하고, 정정이 필요한 경우 Reviewer에게 전달.

### 현재 상태: **Mock (v1)**

**파일**: `app/providers/mock_providers.py`

### 추상 인터페이스

```python
async def check_facts(self, claim: str, context: str = "") -> FactCheckResult
```

### 출력 스키마

| 필드 | 타입 | 설명 |
|------|------|------|
| `verified` | bool | 사실 여부 |
| `confidence` | string | 신뢰도 (low/medium/high) |
| `corrections` | list[string] | 정정 필요 항목 |
| `sources` | list[string] | 검증 출처 URL |
| `raw_response` | string | 원본 응답 |

### 향후 연동 계획
- **Perplexity** API 연동
- 실시간 웹 검색 기반 팩트체크

---

## 7. 파이프라인 흐름

### 6단계 비동기 파이프라인

```
[1] SourceService     소스 DB 저장
         │
         ▼
[2] Researcher        배경 리서치 (Mock → 소스 텍스트 일부로 대체)
         │
         ▼
[3] DraftWriter       초안 생성 (ChatGPT or Claude)
         │              실패 시 → 기본 초안 폴백
         ▼
[4] FactChecker       팩트체크 (Mock → 무시)
         │
         ▼
[5] Reviewer          최종 판단 & 다듬기 (Claude)
         │              리스크 판정 + 텍스트 정제
         │              실패 시 → DraftWriter 결과 직접 사용
         ▼
[6] Classifier        카테고리 & 위험도 최종 확정
                       중복 체크
```

### 오케스트레이션 파일
- `app/orchestrator.py` : 파이프라인 전체 흐름
- 각 단계 실패 시 **폴백** 존재, 전체 파이프라인은 계속 진행

### 재생성 (Regenerate)
텔레그램 승인 카드에서 Regenerate 선택 시 → 원본 소스로 전체 파이프라인 재실행

---

## 8. 프로바이더 설정

### 설정 파일: `app/config.py`

### API 키

| 키 | 용도 | 현재 상태 |
|----|------|----------|
| `openai_api_key` | DraftWriter | 활성 |
| `anthropic_api_key` | Reviewer | 활성 |
| `gemini_api_key` | Researcher | 미사용 |
| `grok_api_key` | TrendHunter | 미사용 |
| `perplexity_api_key` | FactChecker | 미사용 |

### 프로바이더 선택

| 설정 | 옵션 | 기본값 |
|------|------|--------|
| `active_draft_provider` | openai / anthropic / mock | mock |
| `active_research_provider` | gemini / perplexity / mock | mock |
| `active_factcheck_provider` | perplexity / mock | mock |

### 자동 폴백 로직
설정된 프로바이더의 API 키가 없으면 → 자동으로 `mock`으로 폴백

### 상태 확인
`settings.ai_status_summary()` 로 전체 프로바이더 상태 조회 가능

---

## 9. 개선 로드맵

### 즉시 (Phase G)

| 항목 | 대상 파일 | 설명 |
|------|----------|------|
| DraftWriter 프롬프트 강화 | `openai_provider.py` | 훅 공식 추가, AI 표현 금지 목록, 국제 독자 관점 강화 |
| Reviewer `quality_flags` 추가 | `anthropic_provider.py` | "sounds like AI?" 체크, 메타데이터 보강 |
| rate_limiter 외부화 | `rate_limiter.py`, `config.py` | 하드코딩된 제한값 → 설정 파일로 이동 |

### 중기 (Phase H)

| 항목 | 설명 |
|------|------|
| Researcher 실제 연동 | Gemini 또는 Perplexity API |
| FactChecker 실제 연동 | Perplexity API |
| TrendHunter 실제 연동 | Grok (xAI) API |
| `topic_memory.py` | 최근 게시 토픽 기억 (중복 방지) |
| `voice_guard.py` | AI 냄새 나는 표현 감지 |

### 장기

| 항목 | 설명 |
|------|------|
| 프롬프트 A/B 테스트 | 훅 공식/톤 변형 성과 비교 |
| 멀티 프로바이더 폴백 체인 | OpenAI 실패 → Anthropic → Mock |
| 자동 승인 모드 | low risk + evergreen → 자동 게시 (v2) |

---

## 부록: 분류기 (Classifier) 규칙

분류기는 AI가 아닌 **규칙 기반** (`app/services/classifier.py`):

### 카테고리 키워드
- **politics**: election, president, party, ...
- **policy**: policy, regulation, law, ...
- **economy**: economy, gdp, inflation, ...
- **society**: society, demographic, population, ...
- **kpop_culture**: kpop, kdrama, idol, ...
- 매칭 없음 → **evergreen**

### 고위험 키워드
scandal, corruption, arrest, protest, crisis, conflict, death, suicide, abuse, harassment, war, military, nuclear

### 중위험 키워드
debate, criticism, oppose, tension, concern, decline, problem, issue, challenge, risk

### 승인 필요 판단
- v1 기본값: **모든 콘텐츠 승인 필요**
- politics/policy/economy/society/kpop_controversy → 항상 승인 필요
- medium/high risk → 항상 승인 필요
