# TASK_BOARD

이 문서는 **현재 단 1개의 문제** 만 전면에 둔다.
다른 모든 문제는 이 문제가 닫힐 때까지 대기한다.

---

## Updated At
2026-04-10 KST

## Updated By
Claude Code (claude/x-posting-ops-review-7hlxK)

## Current Stage
**레인별 일일 제한 분리 — 서버 반영 완료.** 기존 20/20 상태에서 KO-only 7건+ 차단 없이 통과 확인.

## Current Priority
**없음** — 레인별 제한 서버 반영 완료. 운영자 다음 지시 대기.

## ★ 레인별 일일 제한 분리 (2026-04-10) — 서버 반영 완료
- `app/services/rate_limiter.py` — `can_run_ai_pipeline(source_type)` 추가
  - KO-only 드래프트 제외 카운트 (body prefix 필터)
  - 자동수집: max_ai - manual_reserved(5) 까지
  - 수동입력: max_ai 전체 사용
- `app/orchestrator.py` — rate check Step 0 → Step 2 직전 이동
  - Lane A~C (BREAKING/주간알림/Top5) 항상 실행
  - Lane D (AI 파이프라인)만 레인별 제한
- `scripts/patch_rate_limit_lanes.py` — 서버 전용 패치
- 222 passed, 0 regression
- 서버 반영 명령:
  ```
  cd /root/x-posting-system
  git fetch origin claude/x-posting-ops-review-7hlxK
  git show origin/claude/x-posting-ops-review-7hlxK:app/services/rate_limiter.py > app/services/rate_limiter.py
  git show origin/claude/x-posting-ops-review-7hlxK:scripts/patch_rate_limit_lanes.py > scripts/patch_rate_limit_lanes.py
  /root/x-posting-system/venv/bin/python scripts/patch_rate_limit_lanes.py
  systemctl restart xdashboard
  ```
- 롤백: `cp /tmp/rate_limiter.py.bak.lanes app/services/rate_limiter.py && cp /tmp/orchestrator.py.bak.lanes app/orchestrator.py && systemctl restart xdashboard`

## ★ news_monitor → full_pipeline 통합 (2026-04-10) — 서버 반영 완료
- `app/main.py` — `_news_monitor_loop()` 추가 (APScheduler 대체, 1분 간격)
- `scripts/patch_news_monitor.py` — 서버 전용 패치 (old alert 비활성화 + full_pipeline 연결)
- 자동수집 기사: breaking_classifier 사전 분류 → BREAKING/CANDIDATE만 full_pipeline
- old direct telegram alert 비활성화 (full_pipeline의 Step 1.6/1.5c가 대체)
- 215 passed, 0 regression
- ✅ 서버 반영 완료 (2026-04-10 00:42 UTC)
  - source_items: naver_auto 20건+ 적재
  - candidate_pool_entries: 금융/크립토/주식 다수 적재 (id 16~25)
  - KO-only 라우팅: draft_id 24~43 전부 Pipeline done (KO-only)
  - 영어 approval 카드 0건
  - 일일 제한(20/day) 도달 후 자연 차단 (정상)
  - 롤백: `cp /tmp/main.py.bak.monitor app/main.py && cp /tmp/news_monitor.py.bak.pipeline app/services/news_monitor.py && systemctl restart xdashboard`

## ★ KO-only 분기 미동작 수정 (2026-04-09) — 서버 반영 완료
- `app/services/breaking_classifier.py` (+7줄) — HOLD 가드 내 제목 STRONG 키워드 체크 추가
- Root Cause: MIN_BODY_CHARS=80 가드 → 짧은 본문 HOLD → topic_domain="none" → KO-only 실패
- Fix: 제목에 STRONG 키워드 있으면 CANDIDATE 구제 (EXCLUDE는 여전히 HOLD)
- 207 passed, 0 regression
- ✅ 서버 반영 완료 (2026-04-09 22:31 UTC), smoke test 2건 통과

## ★ /ingest 응답 문구 정합성 수정 (2026-04-09) — 서버 반영 완료
- `app/orchestrator.py` — full_pipeline() 응답 메시지를 처리 경로별 조건 분기로 교체 + docstring 수정
- `app/api/admin.py` — /ingest endpoint docstring 수정
- 변경 전: 모든 경로에서 "초안 생성 완료! 텔레그램에서 승인해주세요." 고정
- 변경 후: BREAKING_NOW/CANDIDATE KO-only / approval 전송 / approval 미전송 4가지 분기
- 206 passed, 0 regression
- ✅ 서버 반영 완료 (2026-04-09 22:07 UTC), smoke test 통과

## ★ 주간 고점수 CANDIDATE 즉시 알림 (2026-04-09) — 서버 반영 완료
- `app/services/daytime_alert_service.py` (신규, ~264줄) — 조건 판정 + 카드 텍스트 + 텔레그램 전송
- `app/orchestrator.py` (+15줄) — Step 1.5c 삽입 (CANDIDATE 블록 내, 1.5b 직후)
- `tests/test_daytime_alert.py` (신규, 26 tests)
- 206 passed, 0 regression
- 서버 반영 대기 (2개 파일: 신규 1 + surgical 1)

## ★ 운영 관측성 수정 (2026-04-09) — 서버 반영 대기
- `app/api/admin.py` (+2/−1) — `text("SELECT 1")` 래핑 (SQLAlchemy 2.x 호환)
- `app/utils/logging_config.py` (1줄) — stdout → stderr (systemd 버퍼링 해소)
- 180 passed, 0 regression
- 서버 반영 대기 (2개 파일 surgical)

## ★ Phase H: 한국어 전용 라인 분기 — 서버 반영 완료 (2026-04-09)
- `app/orchestrator.py` Step 1.7 수술식 삽입 (707→745줄, 3곳)
  - BREAKING_NOW/CANDIDATE + 금융/투자/크립토/주식 → 영어 초안 + 승인 카드 생략
  - HOLD/REJECT/비대상 도메인 → 기존 파이프라인 100% 유지
- `tests/test_ko_routing.py` 신규 (10 tests), 173 passed, 0 regression
- 서버: py_compile OK, xdashboard active (running)

## ★ AI 운영 구조 문서화 완료 (2026-04-09)
- `docs/AI_OPERATING_LAYER.md` 신규 — AI 6축 역할 정의, 네이버 자동수집 라인, BREAKING/Top5/KO-only/승인 관계, 문서 관계도
- 코드 변경 0, 서버 반영 불필요

### 다음 후보 (운영자 택 1)
- 실 기사 인입으로 Phase H 분기 동작 검증
- 05:00 Top5 브리핑 첫 자동 발송 확인
- 후속 보도 자동 트래킹 (24h 윈도우)
- publisher 확장
- 휴지 유지

## ★ Phase G: Dedup/Candidate 영속화 서버 반영 완료 (2026-04-09)
- `app/models/dedup.py` 신규 배치 (3 테이블)
- `app/services/breaking_alert_service.py` 전체 교체 (438→485줄)
- `app/services/top5_briefing_service.py` 전체 교체 (513→643줄)
- `app/db.py` surgical 1줄 삽입
- SQLite 테이블: 7개 (기존 4 + 신규 3) 확인 완료

## ★ Phase F: 05:00 KST 스케줄러 구현 완료 (2026-04-09) — 서버 반영 완료
- `app/main.py` +22줄 — `_top5_scheduler_loop()` + `asyncio.create_task()` 삽입
- `tests/test_top5_scheduler.py` 신규 (9 tests)
- 82 passed, 0 regression
- ✅ 서버 반영 완료 (2026-04-09 20:28 UTC), server.log에서 등록 로그 확인
- ✅ 실측 재확인 (2026-04-09 23:19 UTC): 서버 main.py 스케줄러 코드 존재, 다음 실행 2026-04-11 05:00 KST

## ★ Phase D+E 서버 반영 완료 (2026-04-09)
- Phase D: `top5_briefing_service.py` 서버 배치 (sha256 검증 OK)
- Phase E: orchestrator.py +27줄 수술식 삽입 (680→707줄)
  - Step 1.5b: CANDIDATE → `record_candidate()` 적재
  - Step 1.6 내: BREAKING_NOW → `record_breaking_sent()` Top5 제외 등록
- py_compile OK, grep 검증 OK, xdashboard restart OK

## ★ 05:00 Top5 브리핑 카드 구현 완료 (2026-04-09)
- `app/services/top5_briefing_service.py` 신규 (점수 산정 + 선정 + 카드 + 전송)
- `app/orchestrator.py` Step 1.5b CANDIDATE 적재 + Step 1.6 BREAKING_NOW 제외 등록
- 29 tests passed, 0 regression
- ✅ 서버 반영 완료 (Phase D+E)

### 다음 후보 (운영자 택 1)
- 후속 보도 자동 트래킹 (24h 윈도우)
- dedup 영속화 (DB/Redis 이관, 운영자 승인 필요)
- publisher 확장
- 휴지 유지

## ★ 계정 품질 문서 2종 완료 (2026-04-09)
- ✅ `docs/ACCOUNT_CONSTITUTION.md` (commit `15a4b33`) — 계정 정체성 / 주제 / 금지사항 / 톤·문장·리스크·예시 12 섹션
- ✅ `docs/AI_ROLE_PROMPTS.md` (commit `01632471`) — draft writer / reviewer role prompts (+173 lines)
- → **계정 품질 레이어 문서화 2종 세트 완료.** 현재 기준 문서는 이 2개.
- `README.md` / `COMMANDER_BRIEF.md §7` / `RUNNER_RULES.md §12` 의 옛 방향성 항목은 `ACCOUNT_CONSTITUTION.md` 의 Supersedes 선언으로 대체됨 (별 P0 분기 대상, 본 세션 무수정).

---

## Closed Issues (직전 P0 종결 기록 — 누적식)

### ✅ P0 후보 B — mock_providers kwarg 시그니처 phase-8γ 정합
- 종결 일시 : 2026-04-09 09:12 KST
- 작업물 :
  - `app/providers/mock_providers.py` (+11 / −1) — `MockDraftWriter` / `MockReviewer` 시그니처 widening
  - `tests/test_providers.py` (+20 / −0) — kwargs 수용 boundary test 2개 신규
- 결정적 근거 :
  - 시그니처 진단 : Mock ≡ Base 였으나 OpenAI/Anthropic 는 wide → latent TypeError 가능
  - 패치 후 inspect 비교 : Mock ≡ OpenAI ≡ Anthropic 일치
  - pytest : 9 passed (직전 7 + 신규 2)
- base.py 무수정 (보호 영역)
- 운영자 결정 : "D 다음 B"

### ✅ P0 후보 D — RUNNER_RULES §15 부칙 (drift 재발 방지) 추가
- 종결 일시 : 2026-04-09 09:06 KST
- 작업물 : `RUNNER_RULES.md` §15 신설 (운영자 5개 행위 사전 알림 의무 + Claude Code 측 24h 확인 의무 + 위반 처리 + 한계)
- 결정적 근거 : 후보 A 의 회고 → 운영 절차 drift 가 코드 drift 보다 선행 원인
- 코드 변경 : 0
- 운영자 결정 : "D 먼저가 맞다 ... D 다음 B"

### ✅ P0 후보 A — 서버 anthropic_provider.py 출처 미상 변경 채널 식별
- 종결 일시 : 2026-04-09 09:00 KST
- 결정적 근거 :
  - git reflog 에 `temp/phase8a-observe-bypass-20260408-042459` 임시 브랜치 명시 (Claude Code 자동 명명 패턴)
  - 운영자 자인 ("손댁적 잇고") → D2 단독 가설 배제
  - `.bak` 가 옛 v10 본 (21270 bytes, sha256 다름) → D3 강화
  - 본 GitHub 작업 브랜치 push 18시간 이전에 phase8 코드가 이미 서버 working tree 진입
- 결론 : **D1 (운영자 직접 작업) + D3 (.bak 안전 백업) 결합 채널 단정**
- D2 / D4 / D5 모두 배제
- 코드 변경 0 (실측만)

### ✅ Reviewer JSON 파싱 실패 원인 분리 → H1 (코드 펜스) 확정
- 종결 일시 : 2026-04-09 08:37 KST
- 적용 패치 :
  - `9b5f830` cecd4ab 동등본 (관측 로그) — 36+/1-
  - `b62cc33` dd49fd3 동등본 (sanitize) — 39+/1-
- 결정적 근거 : sanitize 4건 모두 정확히 −12 chars 절감, 4/4 parse 성공
- 결론 : H1 (마크다운 코드 펜스 ` \`\`\`json … \`\`\` `) 확정

---

## Confirmed Facts (현재 시점)

### 안정화 완료 (직전 P0 들 종결)
- `/ingest` 파이프라인 정상
- provider 시그니처 phase-8α 호환
- 텔레그램 카드 전송 정상
- Reviewer JSON 파싱 (H1) sanitize 로 정상화
- DraftWriter / Reviewer 진단 로그 부착 완료
- ★ 서버 drift 채널 단정 (D1 + D3 결합) — P0 후보 A 종결 ★
- ★ RUNNER_RULES §15 부칙 (drift 재발 방지) 추가 — P0 후보 D 종결 ★
- ★ Mock provider kwarg 정합 (Mock ≡ OpenAI ≡ Anthropic) — P0 후보 B 종결 ★

### 작업 브랜치 HEAD (GitHub 기준선)
- 직전 docs HEAD : `735ae15` (P0 후보 D — RUNNER_RULES §15 추가)
- 직전 코드 HEAD : `b62cc33` (anthropic_provider.py 39+/1- sanitize)
- 새 코드 HEAD : (본 P0 B commit 직후 갱신 예정)
- 브랜치 : `claude/x-posting-ops-review-7hlxK`

### Provider 시그니처 정합 현황 (Phase 8-γ 후)
- `Base.generate_draft` : narrow `(title, source_text, language)` — 보호 영역 무수정
- `Mock.generate_draft` ≡ `OpenAI.generate_draft` ≡ `Anthropic.generate_draft`
  : wide `(title, source_text, language, source_type, criteria_context)`
- `Base.review_and_refine` : narrow `(..., factcheck)`
- `Mock.review_and_refine` ≡ `Anthropic.review_and_refine`
  : wide `(..., factcheck, criteria_context)`
- pytest : 9/9 PASSED

---

## Current Issue
**없음 — 운영자 다음 P0 선택 대기**

---

## 다음 후보 (계정 품질 문서 2종 완료 후 — 운영자 1개 선택, NEEDS_HUMAN)

### 후보 G1 — ACCOUNT_CONSTITUTION + AI_ROLE_PROMPTS 기반 실제 작성 워크플로 문서화
- **목표** : 두 문서가 실제 한국어 원문 생성 파이프라인에서 어떻게 호출되고 묶이는지의 워크플로 1장 문서화
- **위험도** : 0 (docs only)
- **범위** : 신규 docs 파일 1개 (예: `docs/WRITING_WORKFLOW.md`) — 코드 무수정
- **이점** : 기준 문서 2종 → 실행 절차 매핑, 손실 없는 재사용 가능
- **단점** : 본 세션에서 확정 금지, 운영자 승인 후 별 세션에서 진입

### 후보 G2 — DraftWriter / Reviewer 실사용 입력 템플릿 문서화
- **목표** : AI_ROLE_PROMPTS 에 대응되는 실사용 입력 템플릿(제목 / 원문 / 해석 축 / 출처 등) 샘플 문서화
- **위험도** : 0 (docs only)
- **범위** : 신규 docs 파일 1개 (예: `docs/INPUT_TEMPLATES.md`) — 코드 무수정
- **이점** : 운영자가 매 입력마다 재구성하지 않도록 템플릿 고정
- **단점** : 본 세션에서 확정 금지, 운영자 승인 후 별 세션에서 진입

### 후보 G3 — 운영 휴지 유지
- **목표** : 현재 휴지 상태 그대로 유지, 운영자 hotfix / §15.1 알림 대기
- **위험도** : 0
- **이점** : 기준선 흐림 방지, 다음 트리거까지 대기
- **단점** : 없음 (기본값)

### 권고
- **NEEDS_HUMAN** — 본 세션에서 다음 후보를 확정하지 않는다.
- 운영자가 G1 / G2 / G3 중 1개 선택해야 진입 가능.
- 새 hotfix 가 있으면 그쪽이 우선.

---

## 이전 P0 후보 (참고용, 종결 또는 보류)

### 후보 C — base.py 시그니처 drift 점검
- **목표** : `app/providers/base.py` 의 추상 시그니처가 concrete 와 narrow 차이를 유지하는 게 의도적인지 점검 + 필요 시 widening
- **위험도** : 중 (보호 영역 — 운영자 사전 승인 필요)
- **범위** : 우선 read-only 점검, 수정은 별도 승인 후
- **이점** : Liskov 측면에서 abstract ≡ concrete 일치, 향후 caller 가 새 kwarg 사용 시 명시적 인터페이스
- **단점** : 보호 영역, 변경 마찰 큼

### 후보 E — 서버 surgical apply (P0 B 결과물)
- **목표** : `mock_providers.py` 1개 파일을 서버에 surgical checkout
- **위험도** : 낮음 (운영 라인 미사용)
- **이점** : 서버 환경에서 키 부재 시 fallback 안전망
- **단점** : 운영 라인은 키 보유 → 즉각적 가치 낮음 → 우선순위 낮음

### 후보 F — 새 hotfix (운영자 발의 시)
- 운영자가 텔레그램/대시보드/로그에서 새 이상을 발견하면 그쪽 우선

### 권고
- **F (새 hotfix) 가 있으면 F 우선**
- 없으면 후보 E (서버 surgical apply, 5분 작업) 또는 후보 C (base.py 점검 read-only)
- C 는 보호 영역이라 사전 승인 필수

---

## Files Forbidden To Change
- `app/orchestrator.py`
- `app/api/admin.py`
- `app/providers/base.py` (후보 C 채택 시 read-only 점검만)
- `app/providers/anthropic_provider.py`
- `app/providers/openai_provider.py`
- `app/providers/ai_provider.py`
- `app/services/*` 전체
- `app/models/*` 전체
- `dashboard/` 전체
- `.env`
- `main` 브랜치
- prompt / model / max_tokens / config
- **서버 wide pull / destructive 명령 일체 금지**

---

## Validation Steps
**N/A — 본 단계는 P0 종결 박제 + 다음 후보 선택 요청만**

---

## Recommendation
**NEEDS_HUMAN** — 계정 품질 문서 2종 완료 박제 + 다음 후보(G1 / G2 / G3) 선택 대기. 버그 휴지 상태는 유지.

운영자 결정 기록 (누적):
- 08:37 KST : 직전 P0 종결, 후보 A/B/C 중 1개 선택 요청
- 08:41 KST : 후보 A 채택 → 실측 명령 발신
- 08:49 KST : 1차 실측 결과 박제, 후보 2개 그룹으로 좁힘
- 09:00 KST : 2차 실측 + 운영자 1줄 회신 → D1+D3 단정, P0 후보 A 종결
- 09:06 KST : "D 다음 B" 결정 → 후보 D 진입+종결 (RUNNER_RULES §15)
- 09:12 KST : 후보 B 종결 (mock_providers kwarg 정합, pytest 9/9)
- 09:16 KST : 오늘 P0 4건 종결, 운영자 결정으로 세션 휴지
- 09:42 KST : 계정 품질 레이어 문서화 전환 → `ACCOUNT_CONSTITUTION.md` 완료 / `AI_ROLE_PROMPTS.md` 부분 중단
- 12:18 KST : `AI_ROLE_PROMPTS.md` 재개 반영 (commit `01632471`)
- 12:25 KST : HANDOFF_LOG 최상단 완료 박제 (commit `90fede1`)
- 12:28 KST : 본 TASK_BOARD 갱신 — 계정 품질 문서 2종 완료 반영, 휴지 유지, NEEDS_HUMAN

다음 세션 트리거:
- 운영자가 다음 후보 (G1 / G2 / G3 / 새 hotfix) 중 1개 선택
- 또는 새 hotfix / §15.1 알림 발생 시 그쪽 우선
- 버그 휴지 상태는 운영자 명시 해제 전까지 유지

---

## Next Handoff Rule
- 운영자 후보 선택 후 다음 세션에서 해당 후보 진입 박제
- 후보 G1 / G2 채택 시 신규 docs 파일 1개만 생성, 코드 무수정
- 후보 G3 채택 시 휴지 유지 (추가 작업 없음)
- 새 hotfix 발생 시 그쪽이 G1/G2/G3 보다 우선
- 이전 P0 후보 (C / E / F) 는 참고용으로만 남김 — 진입 시 별도 운영자 승인 필요
