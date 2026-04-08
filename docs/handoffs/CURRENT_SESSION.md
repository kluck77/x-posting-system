# Current Session — 2026-04-08 (v11d + Phase 1 설계)

## 요약 한 줄
문제 6 (텔레그램 카드 한국어 요약) 패치 완료(커밋 `8616d01`, 원격 push 완료, 서버 적용 pending) +
Phase 1 (네이버 1차 탐지기 → 텔레그램 후보 다이제스트 → 운영자 Pick → AI 호출 게이트) 설계 및
저장 구조(`Option B'` + `candidate_*` 네이밍) 확정. 코드 수정은 문제 6 커밋 1건뿐, 나머지는 전부 문서.

---

## 1. Confirmed Facts

### 역할 / 원칙
- 수석 디버거 + 수석 시스템 설계자로 동작
- 최소 수정 원칙, 원인 단정 금지, `orchestrator.py` / `dashboard/**` / `.env` / 서버 실행 브랜치 / `main` 보호
- 응답 포맷 고정: Confirmed Facts → Root Cause → Minimal Fix Scope → Exact Files → Forbidden → Validation → Recommendation

### 브랜치 상태
- 서버 실행 브랜치: `claude/premium-control-room-ui-LJFba`   (무수정)
- 작업 브랜치:      `claude/setup-opus-model-1tWC7`         (이번 세션 작업)
- 세션 초기에 작업 브랜치를 서버 브랜치 HEAD 로 재설정:
  ```
  git checkout -B claude/setup-opus-model-1tWC7 origin/claude/premium-control-room-ui-LJFba
  ```
- ⚠ upstream 이 `origin/claude/premium-control-room-ui-LJFba` 로 잡혀 있을 수 있음.
  다음 세션에서 push 할 때 반드시:
  ```
  git push -u origin claude/setup-opus-model-1tWC7
  ```

### 완료된 코드 작업 (커밋 1건)
**커밋**: `8616d01`
**메시지**: `feat(telegram): add Korean summary to approval card (problem #6)`

**변경 파일 (2개, +16/-1)**:
- `app/providers/anthropic_provider.py`  (+8 / -0)
- `app/services/telegram_service.py`     (+8 / -1)

**내용**:
- Reviewer 프롬프트에 `korean_summary` 필드 추가
- Reviewer 응답 파싱 시 `🇰🇷 {요약}\n\n{rationale}` 형태로 `ai_rationale` 에 prepend
- `build_approval_card` 가 `🇰🇷` 접두 감지 → 두 섹션 분리 렌더
  (`🇰🇷 한국어 요약:` + `🤖 AI Rationale:`)
- 후방 호환: Reviewer 실패 / 필드 없음 → 기존 단일 블록 그대로 렌더

**로컬 검증 결과**:
- Python 구문 OK (`ast.parse` 통과)
- 렌더링 단위 격리 테스트 4개 케이스 통과:
  - 한국어 + 영어 rationale → 두 섹션 분리
  - 한국어만                → 한국어 섹션만
  - 영어만 (fallback)       → 기존 단일 블록
  - 빈 값                    → 아무 출력 없음

**원격 상태**: `origin/claude/setup-opus-model-1tWC7 = 8616d01` (push 완료)

### 코드 실사로 확정된 사실
- `SourceItem` 테이블명 = `source_items` (`app/models/content.py:63`)
  컬럼: `id, title, url, source_text, source_type, language, created_at`
- `Draft.source_item_id` FK 가 `source_items` 를 참조
- 기존 네이버 수집 구조 존재:
  - `app/services/naver_news.py` (134 lines) — `search_keyword`, `search_all_keywords`
  - `app/services/naver_usage.py` (61 lines)
  - `app/services/news_monitor.py` (360 lines)
    - `run_monitor_cycle()`, `_ingest_article()`
    - in-memory: `_story_clusters`, `_pending_articles`, `_alerted_stories`
    - `overnight_buffer` (22:00~05:00 KST)
    - `_send_news_alert()` (텔레그램 속보)
- `Draft` 의 status 계열 네이밍 관례: `approval_status`, `b2b_status`,
  `premium_status`, `b2b_candidate` — `{도메인}_status` 패턴 확립

### 설계 확정 (문서로만 고정, 코드 0건)
- **Phase 1 베이스**: Option B' — `source_items` 재사용 + nullable 컬럼 3개 추가
- **컬럼명 확정**:
  | 이름 | 타입 | NULL | 의미 |
  |---|---|---|---|
  | `candidate_status` | TEXT | YES | `NULL` / `pending` / `picked` / `skipped` / `muted` / `expired` |
  | `candidate_score`  | INTEGER | YES | rule_filter 점수 |
  | `fetched_at`       | DATETIME | YES | 폴러 수집 시각 (UTC) |
- **의미 분리**: `candidate_status IS NULL` 이면 기존 `/draft`, `/note`, `/ingest` 수동 경로 → 무영향
- **Phase 1 범위**: Sprint-0 (읽기 전용 실사) → Sprint-1 ~ Sprint-6 순차
- **배포 전략**: Round 1 (기능 비활성: DB/필터/수집 저장부만) → Round 2 (다이제스트 + 콜백 + 스케줄러)

### 시스템 운영 철학 재확인
- 네이버 API = "원문 생성기" 아님, "저비용 1차 탐지기" 로만 사용
- AI 호출 = 운영자가 Pick 한 후보에만 발생 (cost gate)
- 기본 라우팅 = OpenAI Draft + Anthropic Review (매건)
- 조건부 라우팅 (Perplexity/Gemini/xAI) = Phase 2 로 이관
- 월 예산 $30 안에서 유지

---

## 2. Pending Items

### 운영자 결정 대기 (모두 의사결정, 코드 수정 아님)
| ID | 항목 | 상태 |
|---|---|---|
| P-1 | 문제 6 패치 서버 적용 | 로컬/원격 push 완료, 서버 적용 `NEEDS_HUMAN` (SSH 권한 없음) |
| P-2 | Phase 1 Sprint-0 실사 착수 승인 | 대기 |
| P-3 | Phase 1 브랜치 전략 (현 브랜치 유지 권장) | 대기 |
| P-4 | Phase 1 보고 주기 (Sprint당 1회 + Round 배포 시 추가 1회 = 총 8회 권장) | 대기 |

### 미해결/미착수 — 이번 세션 범위 외
| ID | 문제 | 상태 / 주의 |
|---|---|---|
| U-1 | 문제 7 — CTA 문구 자동 삽입 | 적용 대기. 수정 후보: `app/providers/openai_provider.py` |
| U-2 | 문제 8 — Reviewer JSON 파싱 오류 `Expecting value: line 1 column 1 (char 0)` | 미해결, 간헐적. **원인 단정 금지, 로그 먼저 확인** |
| U-3 | 문제 9 — FactChecker 401 Unauthorized | 원인 후보: `PERPLEXITY_API_KEY` 미설정/만료. warning, 파이프라인은 진행됨 |

---

## 3. What Was Not Applied To Server Yet

**서버 `/root/x-posting-system` 에 반영되지 않은 것**:
- 문제 6 패치 (커밋 `8616d01`) — 원격에는 올라가 있지만 서버 작업트리는 미반영
  - 대상 파일: `app/providers/anthropic_provider.py`, `app/services/telegram_service.py`
- Phase 1 계획 전부 — 코드 자체가 아직 없음 (설계 문서만)

**이유**: 이 세션 환경은 운영 서버 SSH/원격 실행 채널 없음. 운영자 직접 실행 또는 원격 채널 연결 필요.

**서버 브랜치 `claude/premium-control-room-ui-LJFba` 는 이번 세션 내내 무수정/무 push 상태로 보호됨.**

---

## 4. Exact Next Safe Step

### Option A — 문제 6 서버 적용 (먼저 안정화 확보 권장)

운영자가 서버에서 그대로 실행:

```bash
cd /root/x-posting-system
bash scripts/collect_debug_bundle.sh
git fetch origin claude/setup-opus-model-1tWC7
git checkout origin/claude/setup-opus-model-1tWC7 -- \
  app/providers/anthropic_provider.py \
  app/services/telegram_service.py
git status --short   # 정확히 이 2개 파일만 modified 여야 정상
systemctl restart xdashboard.service
systemctl is-active xdashboard.service
ss -tlnp | grep 8000
tail -f /root/x-posting-system/server.log   # 별도 창
```

**검증**: 실 ingest 1건 후 텔레그램 카드에 다음 두 줄이 함께 보이면 성공

```
🇰🇷 한국어 요약: ...
🤖 AI Rationale: ...
```

**실패 시 즉시 롤백**:
```bash
git fetch origin claude/premium-control-room-ui-LJFba
git checkout origin/claude/premium-control-room-ui-LJFba -- \
  app/providers/anthropic_provider.py \
  app/services/telegram_service.py
systemctl restart xdashboard.service
```

### Option B — Phase 1 Sprint-0 실사 (읽기 전용, 코드 수정 0건)

다음 4가지만 확인:
1. `app/main.py` 에서 `run_monitor_cycle` 이 실제 스케줄되고 있는지
2. `app/services/naver_usage.py` 의 현재 기능 범위 (카운터/제한 포함 여부)
3. `app/config.py` 에 digest/candidate 관련 키가 선점되어 있는지
4. `news_monitor._pending_articles → ContentRequest` 전환 경로 존재 여부

산출: 실사 보고서 (운영자에게 한 번 보고)

### 권장 순서
**A → B** (A 로 서버 안정 확인 후에만 B 착수)

---

## 5. Files Likely Involved Next

### 서버 적용 (Option A) — 수정 없음, 선택 적용만
- `app/providers/anthropic_provider.py`
- `app/services/telegram_service.py`

### Sprint-0 실사 (Option B) — 읽기 전용
- `app/main.py`
- `app/services/naver_usage.py`
- `app/config.py`
- `app/services/news_monitor.py`

### Phase 1 실제 착수 시 수정 예상
| 종류 | 파일 | 예상 변경 |
|---|---|---|
| MODIFY | `app/db.py` | +18/-0 (마이그레이션 3건) |
| MODIFY | `app/models/content.py` | +5/-0 (컬럼 3개) |
| NEW | `app/services/rule_filter.py` | +80~120 |
| MODIFY | `app/services/news_monitor.py` | +20/-0 (저장부 1곳) |
| MODIFY | `app/services/telegram_service.py` | +60/-0 (함수 2개 신설) |
| MODIFY | `app/telegram_bot.py` | +90/-0 (콜백 + 명령) |
| MODIFY | `app/main.py` | +5/-0 (스케줄 등록) |
| MODIFY | `app/config.py` | +10/-0 (키 3~4개) |
| MODIFY | `.env.example` | +6/-0 |
| NEW | `tests/test_rule_filter.py` | - |
| NEW | `tests/test_candidate_digest.py` | - |
| NEW | `tests/test_naver_pending_persistence.py` | - |
| NEW | `tests/test_candidate_callbacks.py` | - |
| NEW | `tests/test_schema_migrations.py` (기존 있으면 append) | - |

### 무수정 (보호 계속)
- `app/orchestrator.py`
- `app/dashboard/**`
- `app/providers/**` (Phase 1 라우팅 미구현)
- `.env` (실 파일)
- 서버 실행 브랜치 자체
- `main` 브랜치

---

## 6. Recommendation

### 다음 세션 시작 시 추천 순서
1. **Option A 먼저**: 문제 6 패치 서버 적용 + 결과 보고
   (이 세션의 유일한 코드 산출물이 서버에서 동작함을 먼저 확정)
2. 결과 받은 뒤 **Sprint-0 실사** 착수 (읽기 전용, 안전)
3. 실사 결과 기준으로 **Sprint-1** (DB 스키마 + 모델) 착수 여부 재판단
4. Phase 1 진행 중에는 **문제 7 / 8 / 9 절대 섞지 말 것** (각각 별도 세션)

### 주의사항
- 다음 세션에서 작업 브랜치 push 시 반드시
  `git push -u origin claude/setup-opus-model-1tWC7` 명시
  (upstream 이 서버 브랜치로 잡혀 있을 수 있음 — 이번 세션에서 확인)
- `.env` / `orchestrator.py` / `dashboard` / `main` 브랜치 영구 보호
- 새 DB 테이블 추가 금지 (nullable 컬럼만)
- 전체 pull / 전체 재배포 금지, 개별 파일 선택 적용 고정
- append-only hack 금지, broad refactor 금지

### 제약 준수 체크
- [x] 코드 수정은 문제 6 커밋 1건 (2 파일, +16/-1)
- [x] 서버 적용 0건 (환경 제약)
- [x] PR 생성 0건
- [x] 새 DB 테이블 0건
- [x] orchestrator / dashboard / .env / main 브랜치 무영향
- [x] approval flow 의미 변경 없음
- [x] 문제 7/8/9 미접촉

---

## Session Closing

이 인수인계 메모는 다음 세션 시작 시 그대로 복붙하거나 요약해서
첫 메시지에 붙이면 문맥을 완전 복원할 수 있습니다.
