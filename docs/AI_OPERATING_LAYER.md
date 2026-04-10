# AI_OPERATING_LAYER

이 문서는 x-posting-system 의 **AI 운영 구조 전체상**을 고정한다.
개별 역할 프롬프트(`AI_ROLE_PROMPTS.md`)나 계정 정체성(`ACCOUNT_CONSTITUTION.md`)은 별도 문서에 있다.
본 문서는 "누가, 무엇을, 어떤 순서로, 왜" 를 1장으로 보여주는 **운영 지도**다.

---

## Updated At
2026-04-10 KST (레인별 일일 제한 분리)

## Updated By
Claude Code (claude/github-mcp-setup-L0oac)

---

## 1. 목적

- 채팅 메모리에 흩어져 있던 AI 운영 구조를 GitHub 문서로 고정한다.
- 새 세션이 열릴 때 "현재 어떤 AI 가 어떤 역할인지" 를 5분 안에 파악할 수 있게 한다.
- 역할 추가/변경 시 본 문서를 먼저 갱신하고 코드를 따라가게 한다.

---

## 2. 전체 운영 구조 개요

```
┌─────────────────────────────────────────────────────────┐
│                    소스 수집 계층                          │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐ │
│  │ 네이버 자동수집 │   │  수동 /ingest │   │ RSS 피드     │ │
│  │ (서버 전용)    │   │  (API/텔레그램)│   │ (서버 전용)   │ │
│  └──────┬───────┘   └──────┬───────┘   └──────┬───────┘ │
│         └──────────────────┼──────────────────┘         │
│                            ▼                            │
│              orchestrator.full_pipeline()                │
└────────────────────────────┬────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────┐
│                  AI 파이프라인 계층                        │
│                                                         │
│  Step 0   일일 제한 확인                                  │
│  Step 1   소스 DB 저장                                   │
│  Step 1.5 BREAKING 분류 (breaking_classifier)            │
│  Step 1.5b CANDIDATE → Top5 야간 큐 적재                  │
│  Step 1.6 BREAKING_NOW → 텔레그램 속보 알림               │
│  Step 1.7 한국어 전용 라인 분기 (금융/투자/크립토/주식)       │
│  Step 2   Researcher — 배경 리서치                        │
│  Step 3   DraftWriter — 초안 생성                         │
│  Step 4   FactChecker — 팩트체크                          │
│  Step 4.5 5-Criteria 품질 필터 (서버 고유)                 │
│  Step 5   Reviewer — 최종 판단 & 다듬기                    │
│  Step 5.5 Reviewer regenerate 루프 (서버 고유)             │
│  Step 6   분류 & 위험도 확정                               │
│           └ community_risk / business_classifier (서버 고유)│
└────────────────────────────┬────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────┐
│                  발행 계층                                │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐   │
│  │ 텔레그램 승인  │  │ X 게시       │  │ Top5 브리핑   │   │
│  │ 카드 전송     │  │ (x_publisher)│  │ (05:00 KST)  │   │
│  └──────────────┘  └──────────────┘  └──────────────┘   │
└─────────────────────────────────────────────────────────┘
```

**핵심 원칙** : 소스가 어디서 왔든 (네이버 자동 / 수동 입력 / RSS) 모두 `orchestrator.full_pipeline()` 한 곳으로 합류한다. 파이프라인 내부에서 분류 결과에 따라 경로가 갈린다.

---

## 3. AI 역할 정의 (6축)

| # | 역할 | 담당 AI / 도구 | 하는 일 | 연결 코드/문서 |
|---|------|---------------|---------|---------------|
| 1 | **리서치 (외부 정보 수집)** | Perplexity | 기사 배경, 맥락, 관련 데이터 조사 | `Researcher.research()` (Step 2) |
| 2 | **X 트렌드 파악** | Grok (X/Twitter) | X 플랫폼 실시간 트렌드, 반응 분석 | `get_trending_topics()` (서버 고유) |
| 3 | **구현 (코드 작업)** | Claude Code | 코드 작성, 테스트, 문서 갱신, 서버 패치 스크립트 생성 | `RUNNER_RULES.md §2` |
| 4 | **전략 (판정/지시)** | GPT | GitHub 문서 기반 판정, 다음 액션 지시, 전략 설계 | `RUNNER_RULES.md §2` |
| 5 | **콘텐츠 생성 (초안/검수)** | 운영용 생성 AI (OpenAI / Anthropic) | 초안 작성 (DraftWriter), 검수 (Reviewer), 팩트체크 (FactChecker) | `AI_ROLE_PROMPTS.md`, `ai_provider.py` |
| 6 | **소스 자동수집** | 네이버 뉴스 API + RSS | 한국 뉴스 자동 수집, 키워드 필터링, 파이프라인 자동 투입 | `news_monitor.py` 등 (서버 전용) |

### 역할 간 관계

```
GPT(전략) ──지시──▶ Claude Code(구현) ──코드──▶ 서버
                                                │
운영자(사람) ──의사결정──▶ 텔레그램 승인/거절         │
                                                │
Perplexity(리서치) ──배경정보──▶ ┐                  │
Grok(트렌드)       ──트렌드──▶  ├── orchestrator ◀─┘
운영용 AI(생성)    ──초안/검수──▶ ┘
네이버(수집)       ──기사원문──▶ orchestrator
```

- **GPT 와 Claude Code 는 파이프라인 밖에서 동작한다.** 운영 판정과 코드 작업만 담당.
- **Perplexity, Grok, 운영용 AI 는 파이프라인 안에서 동작한다.** 각 Step 에서 호출됨.
- **네이버 수집은 파이프라인 입구에서 동작한다.** 수집한 기사를 `full_pipeline()` 에 투입.

---

## 4. 네이버 자동수집 라인

### 4.1 구성 파일 (서버 전용 — 작업 브랜치에 없음)

| 파일 | 역할 |
|------|------|
| `app/services/naver_news.py` | 네이버 뉴스 API 호출, 키워드 검색 |
| `app/services/naver_usage.py` | 네이버 API 일일 할당량 (25,000) 추적 |
| `app/services/news_monitor.py` | 주기적 폴링 오케스트레이션 |
| `app/services/rss_fetcher.py` | RSS 피드 수집 |
| `app/services/content_fetcher.py` | 기사 본문 추출 |

### 4.2 동작 흐름

```
main.py: _news_monitor_loop() (1분 간격, asyncio)
  │
  └─▶ news_monitor.run_monitor_cycle()
        │
        ├─▶ naver_news.py (네이버 뉴스 API 검색)
        │     └─▶ naver_usage.py (할당량 차감)
        │
        ├─▶ rss_fetcher.py (RSS 피드 수집)
        │
        └─▶ 기사별 처리:
              │
              ├─▶ breaking_classifier (사전 분류)
              │     ├─ BREAKING_NOW / CANDIDATE → full_pipeline() 전달
              │     └─ HOLD / REJECT → 건너뜀 (일일 제한 보호)
              │
              └─▶ SourceItemCreate(source_type="naver_auto") 생성
                    │
                    ▼
              orchestrator.full_pipeline()   ← 수동 /ingest 와 동일한 진입점
```

### 4.3 핵심 사항

- 네이버 수집 기사 중 BREAKING_NOW/CANDIDATE 만 `full_pipeline()` 에 투입된다.
- HOLD/REJECT 기사는 건너뛰어 일일 제한(20/day) 을 보호한다.
- 수동 `/ingest` API 와 **완전히 동일한 파이프라인**을 탄다 (BREAKING 알림 / Top5 큐 / 주간 즉시 알림 / KO-only 분기 공유).
- old direct telegram alert (`_send_news_alert()`) 는 비활성화됨 — full_pipeline 이 대체.
- `_news_monitor_loop()` 는 `app/main.py` 에 있으며, `news_monitor.py` 가 없으면 자동 비활성화 (ImportError catch).
- 네이버 API 일일 한도: 25,000 건.
- 서버에만 존재하는 파일이므로 작업 브랜치에서는 실측 불가. `SERVER_STRUCTURE.md §4` 참조.

---

## 5. 수동 /ingest 라인

### 5.1 진입점

```
POST http://localhost:8000/ingest
Body: { "title": "...", "source_text": "...", "url": "...", ... }
```

`app/api/admin.py` 의 `/ingest` 엔드포인트 → `Orchestrator().full_pipeline(data)`.

### 5.2 동작

- 사람이 직접 기사 제목 + 본문 + URL 을 넣는다 (`source_type="manual"`).
- 텔레그램 봇의 `/start`, `/status`, `/pending` 명령은 조회 전용이며, 기사 인입과 무관하다.
- 파이프라인 내부 처리는 네이버 자동수집(`source_type="naver_auto"`)과 100% 동일하다.
- 차이: `source_type` 필드로 수동/자동 구분 가능 (정책은 동일).

---

## 6. 공통 정책 레이어

모든 소스(네이버/수동)에 공통 적용되는 정책.

### 6.1 계정 헌장 (`ACCOUNT_CONSTITUTION.md`)

- 한국어 원문 본체 계정.
- 금융 / 투자 / 크립토 / 주식 해설 전문.
- 단순 뉴스 전달 금지. 해석 중심.
- 가격 추천 / 종목 추천 / 매매 신호 금지.

### 6.2 역할 프롬프트 (`AI_ROLE_PROMPTS.md`)

- DraftWriter system prompt : 3-layer 구조 (팩트 / 해석 / 함의), 4축 분석 (타이밍 / 주체 / 자금흐름 / 심리).
- Reviewer system prompt : 헌장 기반 검수 (PASS / REVISE / REJECT JSON 판정).
- 프롬프트 변경은 `ACCOUNT_CONSTITUTION.md` 갱신 → `AI_ROLE_PROMPTS.md` 동기화 순서.

### 6.3 일일 제한 (`rate_limiter.py`) — 레인별 분리

- AI 파이프라인 제한: Step 2 직전에서 `can_run_ai_pipeline(source_type)` 확인.
- 텔레그램 전송 / X 게시 각각 별도 일일 한도 존재.
- 레인 구조:
  - Lane A (BREAKING_NOW): 무제한 — Step 1.7 이전 리턴
  - Lane B (주간 즉시 알림): 무제한 — Step 1.5c
  - Lane C (Top5 후보 적재): 무제한 — Step 1.5b
  - Lane D-auto (자동수집 AI): `max_ai_drafts - manual_reserved` 까지
  - Lane D-manual (수동 AI): `max_ai_drafts` 전체
- KO-only 드래프트는 AI 카운트에서 제외 (body prefix `"한국어 전용 라인 처리"`).

### 6.4 품질 필터 (서버 고유)

- Step 4.5 : 5-Criteria 품질 점수 (`score_5criteria`). 임계값 미달 시 재생성.
- Step 5.5 : Reviewer regenerate 루프 (`MAX_REGEN_ATTEMPTS=2`).
- `quality_scorer.py`, `voice_guard.py`, `repetition_guard.py` 등 서버 고유 파일.

---

## 7. BREAKING / Top5 / KO-only / Approval 관계

### 7.1 분류 흐름

```
Step 1.5: breaking_classifier.classify_article()
          │
          ├─ BREAKING_NOW ──▶ Step 1.6 속보 텔레그램 알림
          │                   └─▶ record_breaking_sent() (Top5 제외)
          │                   └─▶ Step 1.7 KO-only 판정
          │
          ├─ CANDIDATE ────▶ Step 1.5b record_candidate() (Top5 큐)
          │                   └─▶ Step 1.7 KO-only 판정
          │
          ├─ HOLD ─────────▶ 기존 영어 파이프라인 (Step 2~6 + 승인 카드)
          │
          └─ REJECT ───────▶ 기존 영어 파이프라인 (Step 2~6 + 승인 카드)
```

### 7.2 Step 1.7 한국어 전용 라인 분기 (Phase H)

**조건** : `classification ∈ {BREAKING_NOW, CANDIDATE}` AND `topic_domain ∈ {금융, 투자, 크립토, 주식}`

| 조건 충족 | 동작 |
|----------|------|
| Yes | 영어 초안 파이프라인 (Step 2~6) 전체 생략. 최소 Draft 레코드 생성. `_skip_approval_card=True`. 승인 카드 미전송. |
| No | 기존 파이프라인 100% 유지 (Step 2~6 + 승인 카드). |
| 판정 실패 | fail-open — 기존 파이프라인 계속 진행. |

**`_skip_approval_card`** : Draft 객체의 런타임 속성 (DB 컬럼 아님). `full_pipeline()` 과 `_handle_regenerate()` 에서 확인.

### 7.3 Top5 브리핑 (05:00 KST)

- `_top5_scheduler_loop()` 가 매일 05:00 KST 에 `run_top5_briefing()` 자동 실행.
- CANDIDATE 기사 중 점수 기반 상위 5개 선정 → 텔레그램 브리핑 카드 전송.
- BREAKING_NOW 로 이미 전송된 기사는 `breaking_sent_keys` 테이블로 제외.
- 전송 후 현재 사이클 데이터 삭제.

### 7.4 승인 카드 흐름 (기존)

```
full_pipeline()
  └─ draft 생성 후
       ├─ _skip_approval_card=True  → 승인 카드 미전송 (한국어 전용 라인)
       └─ _skip_approval_card=False → send_for_approval() → 텔레그램 승인 카드
                                       └─ 운영자 approve → X 게시
                                       └─ 운영자 reject  → 거절
                                       └─ 운영자 regenerate → 재생성
```

---

## 8. 금지사항

본 문서의 범위 내 금지사항. `RUNNER_RULES.md` 의 상위 금지사항도 병행 적용.

1. **AI 역할 임의 추가/변경 금지.** 본 문서 갱신 → 운영자 승인 → 코드 반영 순서.
2. **파이프라인 Step 순서 변경 금지.** 기존 Step 사이에만 삽입 허용 (예: Step 4.5).
3. **`_skip_approval_card` 를 DB 컬럼으로 승격 금지.** 런타임 속성으로만 유지.
4. **네이버 자동수집 파일을 작업 브랜치에 복제 금지.** 서버 전용 파일은 서버에서만 관리.
5. **승인 카드 흐름의 의미 변경 금지.** `RUNNER_RULES.md §5` 보호 영역.
6. **`orchestrator.full_pipeline()` 진입점 분리 금지.** 모든 소스는 단일 진입점.

---

## 9. 다음 우선순위

Phase H 완료 후 운영자 선택 대기 상태. 후보 목록:

| 순위 | 후보 | 내용 | 위험도 |
|------|------|------|--------|
| 1 | 실 기사 검증 | Phase H 분기 동작을 실제 금융 기사로 확인 | 0 (관찰만) |
| 2 | 05:00 Top5 첫 발송 확인 | 스케줄러 + 점수 산정 + 카드 전송 end-to-end 검증 | 0 (관찰만) |
| 3 | 후속 보도 자동 트래킹 | 24h 윈도우 내 관련 기사 자동 연결 | 중 (신규 기능) |
| 4 | publisher 확장 | X 게시 기능 강화 | 중 |
| 5 | 휴지 유지 | 현 상태 안정화 관찰 | 0 |

---

## 10. 운영 메모

- **서버-브랜치 divergence** : 서버 orchestrator.py (745줄) ≠ 브랜치 orchestrator.py (417줄). 전체 pull/checkout 절대 금지. (`SERVER_STRUCTURE.md §3`)
- **서버 고유 기능** : 5-Criteria 품질 필터, Reviewer regenerate 루프, community_risk, business_classifier, prediction_service, TrendHunter/Grok 연동 — 모두 서버에만 존재.
- **fail-open 원칙** : 모든 신규 Step (1.5~1.7) 은 `try/except` 로 감싸져 있음. 실패 시 기존 파이프라인 계속 진행.
- **systemd 서비스** : `xdashboard.service` (NOT `x-posting`). `systemctl restart xdashboard` 로 재시작.
- **DB 테이블** : 7개 (source_items, drafts, post_logs, cta_copies + breaking_dedup_entries, candidate_pool_entries, breaking_sent_keys).
- **상위 문서 연결** : `ACCOUNT_CONSTITUTION.md` (계정 정체성) → `AI_ROLE_PROMPTS.md` (프롬프트) → 본 문서 (운영 구조). 충돌 시 상위 문서 우선.

---

## 문서 관계도

```
RUNNER_RULES.md (운영 절대 규칙)
  │
  ├── ACCOUNT_CONSTITUTION.md (계정 정체성 헌법)
  │     └── AI_ROLE_PROMPTS.md (DraftWriter / Reviewer 프롬프트)
  │
  ├── AI_OPERATING_LAYER.md (본 문서 — AI 운영 구조 전체상)
  │
  ├── SERVER_STRUCTURE.md (서버 물리 구조 + 배포 규칙)
  │
  ├── TASK_BOARD.md (현재 작업 1개)
  │
  └── HANDOFF_LOG.md (세션 인계 기록)
```
