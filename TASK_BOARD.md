# TASK_BOARD

이 문서는 **현재 단 1개의 문제** 만 전면에 둔다.
다른 모든 문제는 이 문제가 닫힐 때까지 대기한다.

---

## Updated At
2026-04-09 09:12 KST

## Updated By
Claude Code (claude/x-posting-ops-review-7hlxK)

## Current Stage
**P0 후보 B 종결. 운영자 다음 P0 선택 대기.**

## Current Priority
**NEEDS_HUMAN — 다음 P0 선택 (후보 C 또는 새 hotfix)**

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

## 다음 P0 후보 (운영자 1개 선택)

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
**APPROVE (P0 후보 B 종결 박제) + NEEDS_HUMAN (다음 P0 선택)**

운영자 결정 기록 (누적):
- 08:37 KST : 직전 P0 종결, 후보 A/B/C 중 1개 선택 요청
- 08:41 KST : 후보 A 채택 → 실측 명령 발신
- 08:49 KST : 1차 실측 결과 박제, 후보 2개 그룹으로 좁힘
- 09:00 KST : 2차 실측 + 운영자 1줄 회신 → D1+D3 단정, P0 후보 A 종결
- 09:06 KST : "D 다음 B" 결정 → 후보 D 진입+종결 (RUNNER_RULES §15)
- 09:12 KST : 후보 B 종결 (mock_providers kwarg 정합, pytest 9/9)

다음 세션 트리거:
- 운영자가 다음 P0 (C / E / F / 새 hotfix) 중 1개 선택
- 또는 새 hotfix 발생 시 그쪽 우선

---

## Next Handoff Rule
- 운영자 후보 선택 후 다음 세션에서 해당 후보 P0 진입 박제
- 후보 C 채택 시 read-only 점검 먼저, 수정은 별도 승인
- 후보 E 채택 시 서버 surgical checkout 1개 파일 (`mock_providers.py`)
- 후보 F (새 hotfix) 채택 시 새 P0 진입 절차
