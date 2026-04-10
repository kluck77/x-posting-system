# AI 역할 프롬프트 세트 문서

> x-posting-system의 AI 역할 구조와 프롬프트 명세
> 최종 수정: 2026-04-10
> 상태: 완료

---

## 1. 목적

이 문서는 x-posting-system에서 사용하는 AI 역할의 구조, 프롬프트, 운영 기준을 정리한다.

대상 독자:
- 다음 작업자 (Claude Code, GPT, 사람 운영자)
- 프롬프트를 수정하거나 새 역할을 추가할 때 기준으로 사용

이 문서가 다루는 것:
- 운영 관점 역할 구분과 코드 관점 모듈 구분
- 각 역할의 프롬프트 원문, 출력 스키마, 상태
- 공통 운영 기준 (금지 사항, 톤, 언어)

이 문서가 다루지 않는 것:
- 서버 배포/인프라 → CLAUDE_CODE_HANDOFF.md
- 작업 진행 현황 → TASK_BOARD.md
- 시스템 아키텍처 전반 → COMMANDER_BRIEF.md

---

## 2. 공통 운영 기준

이 시스템의 모든 AI 역할에 공통 적용되는 기준이다.

### 계정 정체성

- 한국 금융/경제/정책 이슈를 해석하는 계정
- 뉴스 요약이 아니라 **"돈의 의미 해석"** 중심
- credibility > virality

### 언어 기준

- 운영 언어: **한국어 기본**
- 영어 콘텐츠: 해외 독자용 별도 레인에서만 생성
- 한국 독자 기준 우선, 필요 시 해외 독자 맥락 보조

### 콘텐츠 필수 요건

- 첫 문장은 바로 핵심/결론
- 모든 글에 시장/자본 의미 해석 1줄 이상 포함
- 불필요하게 장황한 문장 금지

### 금지 주제

| 금지 항목 | 이유 |
|----------|------|
| 정치 공방 | 계정 정체성과 무관 |
| 연예/사회 일반 | 금융 계정 범위 밖 |
| 밈코인 | 신뢰도 훼손 |
| 잡주 추천 | 신뢰도 훼손 |
| 전망성 기사 | 근거 없는 추정 |
| 출처 약한 수치 | 팩트 기반 원칙 위반 |

### 금지 문체

| 금지 표현 유형 | 예시 |
|---------------|------|
| AI 티 나는 도입부 | "It's worth noting that...", "In today's rapidly..." |
| 과잉 수식어 | "groundbreaking", "unprecedented", "game-changing" |
| 모호한 전망 | "~할 것으로 보인다", "향후 주목된다" |
| 불필요한 요약 반복 | 결론에서 본문을 다시 되풀이 |
| 감탄형 마무리 | "Only time will tell!", "Stay tuned!" |

### 상태 라벨 정의

이 문서에서 각 역할/모듈의 현재 상태를 아래 라벨로 표시한다.

| 라벨 | 의미 |
|------|------|
| **LIVE** | 서버에서 실제 사용 중 |
| **PARTIAL** | 일부 기능만 실제 사용, 나머지 제한적 |
| **MOCK** | 인터페이스와 더미 데이터만 존재 |
| **PLANNED** | 문서상 계획만 있음, 코드 없음 |

---

## 3. 운영 관점 5역할 vs 코드 관점 내부 모듈

### 왜 구분이 필요한가

운영자가 보는 "AI 5역할"과 코드 안의 "내부 모듈" 수가 다르다.
이 차이를 모르면 "우리는 5명인데 왜 문서에 6~7개가 있지?" 하고 혼동한다.

### 운영 관점: 5역할

시스템 운영에 참여하는 AI 주체 5개를 가리킨다.

| # | 역할 | 담당 | 현재 상태 |
|---|------|------|----------|
| 1 | **Perplexity** | 코드 전체 검토, 인수인계 문서 작성 | LIVE |
| 2 | **Grok** | 실시간 X 트렌드 탐지, 속보 소스 | PARTIAL — 수동 활용만 |
| 3 | **Claude Code** | 서버 배포, 코드 수정, 테스트, 반영 이력 관리 | LIVE |
| 4 | **GPT** | 구조 총괄, 우선순위, 프롬프트 설계, 결과 검수 | LIVE |
| 5 | **생성 AI (ChatGPT/Claude API)** | 파이프라인 내 초안 작성, 리뷰 실행 | LIVE |

### 코드 관점: 내부 모듈 (서브에이전트)

`app/providers/` 아래에 정의된 파이프라인 내부 모듈이다.
운영 관점 역할과 1:1 대응이 아니다.

| 모듈 | 책임 | 상태 | 프로바이더 |
|------|------|------|-----------|
| **DraftWriter** | 초안 작성 | LIVE | ChatGPT (gpt-4o-mini) 또는 Claude |
| **Reviewer** | 리스크 판단, 텍스트 다듬기 | LIVE | Claude (claude-sonnet-4-20250514) |
| **Researcher** | 배경 리서치, 데이터 수집 | MOCK | 더미 반환 (향후 Gemini/Perplexity) |
| **TrendHunter** | 실시간 트렌드 탐지 | MOCK | 더미 반환 (향후 Grok) |
| **FactChecker** | 팩트체크, 출처 찾기 | MOCK | 더미 반환 (향후 Perplexity) |
| **Classifier** | 카테고리/위험도 분류 | LIVE | 규칙 기반 (AI 아님) |

### 대응 관계

```
운영 관점                    코드 관점 내부 모듈
─────────────────────────    ─────────────────────────
Perplexity                → (파이프라인 외부, 인수인계 전용)
Grok                      → TrendHunter [MOCK — 향후 연동]
Claude Code               → (파이프라인 외부, 배포/관리 전용)
GPT                       → (파이프라인 외부, 설계/검수 전용)
생성 AI (ChatGPT/Claude)  → DraftWriter [LIVE]
                          → Reviewer [LIVE]
                          → Researcher [MOCK]
                          → FactChecker [MOCK]
(규칙 기반, AI 아님)       → Classifier [LIVE]
```

### 핵심 포인트

- 운영 5역할 중 파이프라인 코드 안에서 직접 실행되는 것은 **생성 AI** 1개뿐
- Perplexity, Grok, Claude Code, GPT는 파이프라인 밖에서 운영 지원
- Classifier는 AI가 아닌 규칙 기반이지만 파이프라인 내부 모듈에 포함
- 따라서 "운영 5역할 = 코드 6모듈"이 아니라, 관점이 다른 별개 분류

---

## 4. DraftWriter — 초안 작성 모듈

> 상태: **LIVE** | 프로바이더: ChatGPT (gpt-4o-mini) 또는 Claude
> 파일: `app/providers/openai_provider.py`, `app/providers/anthropic_provider.py`

### 역할 정의

소스(뉴스, 링크, 메모)를 받아 X 포스트 **초안**을 생성한다.
최종 판단은 Reviewer가 하므로, DraftWriter는 빠르고 정확한 1차 생성에 집중한다.

### 운영 작성 기준

DraftWriter가 반드시 지켜야 할 기준이다. 프롬프트 개선 시 이 항목을 반영해야 한다.

**필수 규칙:**

| # | 규칙 | 설명 |
|---|------|------|
| 1 | 한국어 기본 | 운영 언어는 한국어. 영어는 해외 레인 전용 |
| 2 | 첫 문장 = 결론/핵심 | 도입부 없이 바로 핵심부터 |
| 3 | 시장/자본 의미 필수 | 모든 글에 "왜 돈이 움직이는가" 해석 1줄 이상 |
| 4 | 숫자/근거 앞쪽 배치 | 구체적 수치가 있으면 글 앞부분에 배치 |
| 5 | "왜 중요한가" 필수 | 이유 없는 팩트 나열 금지 |
| 6 | 필요 시 해외 맥락 보조 | 한국 독자 기준 우선, 글로벌 맥락은 보조적으로만 |

**금지 규칙:**

| # | 금지 항목 | 나쁜 예시 |
|---|----------|----------|
| 1 | 단순 뉴스 요약 | "A가 B를 발표했다. C는 D라고 말했다." (끝) |
| 2 | AI 티 나는 도입부 | "최근 들어~", "주목할 만한~", "It's worth noting~" |
| 3 | 과잉 수식어 | "획기적인", "전례 없는", "game-changing" |
| 4 | 모호한 전망 | "향후 주목된다", "귀추가 주목된다" |
| 5 | 감탄형 마무리 | "지켜볼 필요가 있다!", "Stay tuned!" |
| 6 | 행동 불가능한 추상 문장 | "다양한 의견이 있다", "여러 요인이 작용한다" |
| 7 | 단순 번역/복붙 | 소스 기사를 문장 단위로 옮겨 적는 것 |

### 현재 시스템 프롬프트 (OpenAI)

> 아래는 `app/providers/openai_provider.py`에 현재 배포된 프롬프트 원문이다.
> 운영 작성 기준과 차이가 있으며, 향후 프롬프트 개선 시 위 기준을 반영해야 한다.

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

> `app/providers/anthropic_provider.py` — DraftWriter 역할로 사용 시

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

### 현재 프롬프트 vs 운영 기준 격차

| 운영 기준 | 현재 프롬프트 반영 여부 |
|----------|----------------------|
| 한국어 기본 | **미반영** — 영어 전용으로 작성됨 |
| 첫 문장 = 결론 | **미반영** — "Hook should grab attention"만 있음 |
| 시장/자본 의미 필수 | **미반영** |
| AI 표현 금지 | **미반영** — 금지 목록 없음 |
| 단순 요약 금지 | **미반영** — "Be factual and balanced"만 있음 |
| 숫자 앞쪽 배치 | **미반영** |
| 금지 주제 | **미반영** |

> 이 격차는 프롬프트 코드 개선 시 해소한다. 이 문서는 기준을 정의하는 역할이다.

### 출력 스키마

| 필드 | 타입 | 설명 |
|------|------|------|
| `hook` | string | 오프닝 라인 |
| `body` | string | X 본문 (270자 이하) |
| `thread_continuation` | string/null | 스레드 연속 텍스트 |
| `category_suggestion` | enum | politics/policy/economy/society/kpop_culture/evergreen |
| `tone_notes` | string | 톤 선택 메모 |

### API 호출 스펙

| 항목 | OpenAI | Anthropic |
|------|--------|-----------|
| 모델 | gpt-4o-mini | claude-sonnet-4-20250514 |
| Temperature | 0.7 | 기본값 |
| Timeout | 60s | 60s |
| 응답 형식 | JSON mode 강제 | JSON 지시 |

### 에러 처리

- API 실패 → 기본 초안 폴백 (`"Developing story about: {title}"`)
- JSON 파싱 실패 → 동일 폴백

---

## 5. Reviewer — 리뷰 & 안전 판단 모듈

> 상태: **LIVE** | 프로바이더: Claude (claude-sonnet-4-20250514)
> 파일: `app/providers/anthropic_provider.py`

### 역할 정의

DraftWriter 초안을 받아 **"이 글이 우리 계정에 맞는가"**를 판단한다.
단순 문법 교정이 아니라, 계정 정체성/신뢰도/운영 기준 적합성을 심사하는 역할이다.

### 심사 기준 (Quality Flags)

Reviewer가 초안을 심사할 때 체크해야 할 항목이다.
향후 프롬프트에 `quality_flags` 필드로 반영할 기준이기도 하다.

**필수 체크 항목:**

| # | 체크 항목 | 판단 질문 |
|---|----------|----------|
| 1 | AI 냄새 | 이 글이 AI가 쓴 것처럼 읽히는가? |
| 2 | 단순 요약 여부 | 뉴스 요약만 하고 끝났는가? 해석이 있는가? |
| 3 | 시장/자본 연결 | "왜 돈이 움직이는가" 해석이 1줄 이상 있는가? |
| 4 | 장황함 | 같은 말을 반복하거나 불필요하게 긴가? |
| 5 | 과장/추정 | 근거 없는 전망이나 과장 표현이 있는가? |
| 6 | 금지 주제 위반 | 정치 공방, 밈코인, 잡주 추천 등 금지 주제에 해당하는가? |
| 7 | 팔로우 가치 | 이 글을 보고 계정을 팔로우할 이유가 생기는가? |
| 8 | 행동 가능성 | 독자가 가져갈 수 있는 관찰 포인트가 있는가? |
| 9 | 금지 문체 위반 | AI 도입부, 과잉 수식어, 감탄형 마무리 등이 있는가? |

**판정 결과:**

각 항목은 `pass` / `warn` / `fail` 중 하나로 판정한다.
- `fail` 1개 이상 → `recommended_action: reject`
- `warn` 2개 이상 → `recommended_action: review`
- 모두 `pass` → `recommended_action: approve`

### 현재 시스템 프롬프트

> 아래는 `app/providers/anthropic_provider.py`에 현재 배포된 프롬프트 원문이다.

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

### 현재 프롬프트 vs 심사 기준 격차

| 심사 기준 | 현재 프롬프트 반영 여부 |
|----------|----------------------|
| AI 냄새 체크 | **미반영** |
| 단순 요약 여부 | **미반영** |
| 시장/자본 연결 | **미반영** |
| 장황함 체크 | **미반영** |
| 과장/추정 체크 | **일부** — "NEVER sensationalize"만 있음 |
| 금지 주제 위반 | **미반영** — 카테고리별 리스크만 있음 |
| 팔로우 가치 | **미반영** |
| 행동 가능성 | **미반영** |
| 금지 문체 위반 | **미반영** |
| quality_flags 필드 | **미반영** — 출력에 없음 |

> 이 격차는 프롬프트 코드 개선 시 해소한다. 이 문서는 심사 기준을 정의하는 역할이다.

### 안전 규칙 매트릭스

| 카테고리 | 최소 리스크 | 비고 |
|----------|-----------|------|
| politics | medium | 항상 |
| policy | medium | 항상 |
| economy | medium | 항상 |
| society | medium | 항상 |
| kpop_culture (논란) | medium | 논란 포함 시 |
| evergreen | low | 교육 콘텐츠 |

### 현재 출력 스키마

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

### 향후 추가 예정 출력 필드

| 필드 | 타입 | 설명 |
|------|------|------|
| `quality_flags` | object | 심사 항목별 pass/warn/fail 결과 |
| `quality_flags.ai_smell` | enum | AI 냄새 판정 |
| `quality_flags.summary_only` | enum | 단순 요약 여부 |
| `quality_flags.market_link` | enum | 시장/자본 연결 여부 |
| `quality_flags.verbose` | enum | 장황함 여부 |
| `quality_flags.speculation` | enum | 과장/추정 여부 |
| `quality_flags.banned_topic` | enum | 금지 주제 위반 여부 |
| `quality_flags.follow_worthy` | enum | 팔로우 가치 여부 |
| `quality_flags.actionable` | enum | 행동 가능 관찰 포인트 여부 |
| `quality_flags.banned_style` | enum | 금지 문체 위반 여부 |

### 에러 처리

- Reviewer 실패 → DraftWriter 결과를 직접 사용 (risk=medium, action=review)

---

## 6. Researcher — 배경 리서치 모듈

> 상태: **MOCK** | 프로바이더: 더미 반환 (향후 Gemini / Perplexity)
> 파일: `app/providers/mock_providers.py`, 인터페이스: `app/providers/base.py`

### 역할 정의

주어진 토픽에 대한 배경 정보, 핵심 사실, 출처를 수집하여 DraftWriter와 Reviewer에게 전달한다.

### 현재 실제 사용 수준

**MOCK 상태** — 인터페이스와 더미 데이터만 존재한다.
- 파이프라인에서 호출은 되지만 하드코딩된 더미 텍스트를 반환
- 실제 외부 API 호출 없음
- 실패해도 파이프라인은 계속 진행 (소스 텍스트 일부로 대체)

### 입력 / 출력

| 구분 | 내용 |
|------|------|
| 입력 | `query` (검색 키워드), `context` (추가 맥락) |
| 출력 | `summary` (주제 요약), `key_facts` (핵심 사실 목록), `sources` (참고 URL) |

### 금지사항

- LIVE처럼 표기하거나 실제 리서치가 수행된다고 오해하게 쓰지 말 것
- Mock 상태에서 리서치 결과를 신뢰하지 말 것

### 향후 계획

- Gemini 또는 Perplexity API 연동 예정
- 연동 시 한국어 소스 → 영어 컨텍스트 변환 역할 수행

---

## 7. TrendHunter — 트렌드 탐지 모듈

> 상태: **MOCK** | 프로바이더: 더미 반환 (향후 Grok/xAI)
> 파일: `app/providers/mock_providers.py`, 인터페이스: `app/providers/base.py`

### 역할 정의

X/소셜 미디어에서 실시간 트렌딩 토픽을 탐지하여 콘텐츠 타이밍과 주제 선정에 활용한다.

### 현재 실제 사용 수준

**MOCK 상태** — 인터페이스와 더미 데이터만 존재한다.
- 하드코딩된 트렌드 목록 반환
- 실제 X 트렌드 데이터 없음
- 운영 관점에서 Grok은 수동 활용만 하고 있음 (파이프라인 연동 아님)

### 입력 / 출력

| 구분 | 내용 |
|------|------|
| 입력 | `topic_area` (탐색 영역, 기본값 "korea") |
| 출력 | `trending_topics` (트렌딩 토픽 목록), `relevance_notes` (관련성 메모) |

### 금지사항

- 운영 관점의 Grok 수동 활용과 코드 모듈의 TrendHunter를 혼동하지 말 것
- Mock 결과를 실제 트렌드로 취급하지 말 것

### 향후 계획

- Grok (xAI) API 연동 예정
- X 플랫폼 네이티브 트렌드 데이터 활용

---

## 8. FactChecker — 팩트체크 모듈

> 상태: **MOCK** | 프로바이더: 더미 반환 (향후 Perplexity)
> 파일: `app/providers/mock_providers.py`, 인터페이스: `app/providers/base.py`

### 역할 정의

DraftWriter 초안의 주장(claim)을 검증하고, 정정이 필요한 경우 Reviewer에게 전달한다.

### 현재 실제 사용 수준

**MOCK 상태** — 인터페이스와 더미 데이터만 존재한다.
- 항상 `verified=True`, `confidence="low"` 반환
- 실제 검증 없음
- 실패해도 파이프라인은 계속 진행 (무시)

### 입력 / 출력

| 구분 | 내용 |
|------|------|
| 입력 | `claim` (검증 대상 주장), `context` (추가 맥락) |
| 출력 | `verified` (사실 여부), `confidence` (신뢰도), `corrections` (정정 항목), `sources` (출처 URL), `raw_response` (원본 응답) |

### 금지사항

- Mock 결과의 `verified=True`를 팩트체크 완료로 취급하지 말 것
- 실제 검증이 필요한 민감한 주장은 사람이 직접 확인할 것

### 향후 계획

- Perplexity API 연동 예정
- 실시간 웹 검색 기반 팩트체크

---

## 9. 파이프라인 흐름

### 수동 입력 흐름 (/ingest)

운영자가 텔레그램 또는 API로 직접 소스를 입력하는 경우:

```
운영자 → /ingest (URL, 메모 등)
  → SourceService: 소스 DB 저장
  → Researcher: 배경 리서치 [MOCK — 더미 반환]
  → DraftWriter: 초안 생성 [LIVE — ChatGPT/Claude]
  → FactChecker: 팩트체크 [MOCK — 더미 반환]
  → Reviewer: 리스크 판단 & 다듬기 [LIVE — Claude]
  → Classifier: 카테고리/위험도 확정 [LIVE — 규칙 기반]
  → 텔레그램 승인 카드 전송
  → 운영자 승인/거절/보류/재생성
```

### 자동수집 흐름 (news_monitor)

네이버 뉴스 자동수집 → full_pipeline 통합 경로:

```
news_monitor: 네이버 뉴스 자동수집
  → 키워드 매칭 & 점수 산정
  → 분류 판정:
      BREAKING (score ≥ 85) → Lane A: 즉시 알림 (무제한)
      고점수 (score ≥ 70)  → Lane B: 주간 즉시 알림 (무제한)
      CANDIDATE            → Lane C: Top5 후보 적재 (무제한)
  → 각 레인별 처리:
      Lane A/B → 텔레그램 즉시 알림
      Lane C   → candidate_pool_entries DB 적재
               → 05:00 KST Top5 스케줄러가 상위 5건 발송
```

### 레인별 일일 제한

| 레인 | 용도 | 일일 제한 |
|------|------|----------|
| Lane A | BREAKING 즉시 알림 | 무제한 |
| Lane B | 주간 고점수 즉시 알림 | 무제한 |
| Lane C | Top5 후보 적재 | 무제한 |
| Lane D | AI 파이프라인 (초안→승인) | 자동수집 max-5 / 수동 무제한 |

### KO-only / 영어 분기

- 한국어(KO) 콘텐츠: 정상 처리
- 영어 콘텐츠: 승인 카드 우회 (영어 approval 카드 0건 확인됨)

### 어떤 단계에서 어떤 모듈이 개입하는가

```
소스 입력 ─── SourceService (DB 저장)
    │
    ├─ Researcher [MOCK]
    │
    ├─ DraftWriter [LIVE] ← 여기서 초안 생성
    │
    ├─ FactChecker [MOCK]
    │
    ├─ Reviewer [LIVE] ← 여기서 리스크 판단 + 텍스트 정제
    │
    ├─ Classifier [LIVE] ← 여기서 카테고리/위험도 확정
    │
    └─ 텔레그램 승인 카드 → 운영자 판단
```

### 에러 시 폴백

| 단계 | 실패 시 |
|------|--------|
| Researcher | 소스 텍스트 일부로 대체, 계속 진행 |
| DraftWriter | 기본 초안 폴백 생성, 계속 진행 |
| FactChecker | 무시, 계속 진행 |
| Reviewer | DraftWriter 결과 직접 사용 (risk=medium) |
| Classifier | 기본값 적용 |

---

## 10. 프로바이더 설정

### 프로바이더 — 역할 연결

| 프로바이더 | 연결 역할 | 현재 상태 | 용도 |
|-----------|----------|----------|------|
| **OpenAI** (gpt-4o-mini) | DraftWriter | LIVE | 초안 작성 메인 |
| **Anthropic** (claude-sonnet-4-20250514) | Reviewer, DraftWriter(대안) | LIVE | 리뷰 메인, 초안 대안 |
| **Gemini** | Researcher | PLANNED | 배경 리서치 (미연동) |
| **Grok** (xAI) | TrendHunter | PLANNED | 트렌드 탐지 (미연동) |
| **Perplexity** | FactChecker, Researcher | PLANNED | 팩트체크/리서치 (미연동) |

### API 키 현황

| 키 | 용도 | 현재 상태 |
|----|------|----------|
| `openai_api_key` | DraftWriter | 활성 |
| `anthropic_api_key` | Reviewer | 활성 |
| `gemini_api_key` | Researcher | 미설정 |
| `grok_api_key` | TrendHunter | 미설정 |
| `perplexity_api_key` | FactChecker | 미설정 |

### 프로바이더 선택 설정

설정 파일: `app/config.py`

| 설정 | 옵션 | 기본값 |
|------|------|--------|
| `active_draft_provider` | openai / anthropic / mock | mock |
| `active_research_provider` | gemini / perplexity / mock | mock |
| `active_factcheck_provider` | perplexity / mock | mock |

### 폴백 로직

- 설정된 프로바이더의 API 키가 없으면 → 자동으로 `mock`으로 폴백
- `settings.ai_status_summary()`로 전체 프로바이더 상태 조회 가능

---

## 11. 개선 로드맵

### 원칙

- 현재 운영 품질 개선이 먼저
- 새 기능 추가는 뒤
- 대시보드는 마지막
- 과장된 미래 계획 금지

### 우선순위

| 순위 | 항목 | 대상 | 상태 |
|------|------|------|------|
| 1 | 운영 문서 완성 | 이 문서 (AI_ROLE_PROMPT_SET.md) | 완료 |
| 2 | DraftWriter 프롬프트 코드 반영 | `openai_provider.py` | 대기 — §4 운영 기준 기반 |
| 3 | Reviewer 프롬프트 코드 반영 | `anthropic_provider.py` | 대기 — §5 quality_flags 기반 |
| 4 | 실운영 검증 결과 반영 | Top5 자동 발송 등 | 대기 — 04/11 05:00 KST 검증 |
| 5 | rate_limiter 외부화 | `rate_limiter.py`, `config.py` | 대기 |
| 6 | 대시보드 | 별도 트랙 | 마지막 |

### DraftWriter 프롬프트 개선 시 반영할 항목

§4 격차표 기준:
- 한국어 기본 언어 설정
- 첫 문장 = 결론 지시
- 시장/자본 의미 필수 지시
- AI 표현 금지 목록
- 단순 요약 금지 지시
- 숫자 앞쪽 배치 지시
- 금지 주제 목록

### Reviewer 프롬프트 개선 시 반영할 항목

§5 격차표 기준:
- `quality_flags` 출력 필드 추가
- AI 냄새 체크 지시
- 단순 요약 여부 체크
- 시장/자본 연결 체크
- 장황함 체크
- 과장/추정 체크
- 금지 주제 위반 체크
- 팔로우 가치 체크
- 행동 가능성 체크
- 금지 문체 위반 체크

### 중기 과제 (프롬프트 안정화 이후)

| 항목 | 설명 |
|------|------|
| Researcher 실연동 | Gemini 또는 Perplexity API |
| FactChecker 실연동 | Perplexity API |
| TrendHunter 실연동 | Grok (xAI) API |
| `topic_memory.py` | 최근 게시 토픽 기억 (중복 방지) |
| `voice_guard.py` | AI 냄새 나는 표현 자동 감지 |
