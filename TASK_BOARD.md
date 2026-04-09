# TASK_BOARD

이 문서는 **현재 단 1개의 문제** 만 전면에 둔다.
다른 모든 문제는 이 문제가 닫힐 때까지 대기한다.

---

## Updated At
2026-04-09 09:00 KST

## Updated By
Claude Code (claude/x-posting-ops-review-7hlxK)

## Current Stage
**P0 후보 A 종결 완료.** drift 채널을 D1 + D3 결합으로 단정. 다음 P0 운영자 선택 대기.

## Current Priority
**NEEDS_HUMAN — 다음 P0 후보 (B / C / D) 중 1개 선택**

---

## Closed Issues (직전 P0 종결 기록 — 누적식)

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
- ★ 서버 drift 채널 단정 완료 (D1 + D3 결합) ★

### 작업 브랜치 HEAD (GitHub 기준선)
- 직전 docs HEAD : `d2d949c` (P0 후보 A 1차 실측 박제)
- 직전 코드 HEAD : `b62cc33` (anthropic_provider.py 39+/1- sanitize)
- 현재 시점 서버 == GitHub `b62cc33` byte-identical (1차 실측 확인)
- 브랜치 : `claude/x-posting-ops-review-7hlxK`

### Drift 채널 단정 (P0 후보 A 종결 결과)
- ★ **D1 (운영자 직접 작업) + D3 (.bak 안전 백업) 결합** ★
- 결정적 근거 :
  - git reflog : `temp/phase8a-observe-bypass-20260408-042459` (Claude Code 자동 명명)
  - 운영자 자인 : "손댁적 잇고"
  - `.bak` = 옛 v10 본 (21270 bytes, sha256 167ed967..., 현재 본과 다름)
  - phase8 코드가 GitHub 작업 브랜치 push 18시간 이전에 서버 working tree 진입
- D2 (다른 세션 단독), D4 (직접 업로드), D5 (자동화 hook) 모두 배제

---

## Current Issue
**없음 — 운영자 다음 P0 선택 대기**

---

## 다음 P0 후보 (운영자 1개 선택)

### 후보 B — mock_providers kwarg 시그니처 phase-8α 정합
- **목표** : `MockReviewer.review_and_refine()` 등 mock 5종이 phase-8α 시그니처 (`criteria_context` kwarg) 와 100% 정합한지 검증 + 누락 시 보강
- **위험도** : 낮음 (운영 라인 미사용, 키 부재 시 fallback 만)
- **범위** : `app/providers/mock_providers.py` 1개 파일 / `tests/test_providers.py` 1개 파일
- **검증** : pytest 5종 mock 통과
- **이점** : 다음 통합 테스트 / 키 부재 환경 / 로컬 dev 안정화
- **단점** : 운영 라인에 직접 영향 없음 (우선순위 낮음 가능)

### 후보 C — base.py 시그니처 drift 점검
- **목표** : `app/providers/base.py` 의 `BaseDraftWriter` / `BaseReviewer` 추상 시그니처가 OpenAI/Anthropic 구현체와 일치하는지 점검
- **위험도** : 중 (RUNNER_RULES 보호 영역 — 사전 승인 필요)
- **범위** : 점검은 read-only, 수정은 운영자 승인 후
- **이점** : 다음 phase8γ 작업 전 안전망 확보
- **단점** : 보호 영역이라 작업 마찰 큼

### 후보 D — RUNNER_RULES 부칙 (drift 재발 방지 가드레일)
- **목표** : 운영자가 임시 브랜치 + .bak + 직접 surgical checkout 작업을 했을 때 채팅에 즉시 알리도록 하는 운영 약속을 RUNNER_RULES 에 부칙으로 추가
- **위험도** : 0 (문서만)
- **범위** : `RUNNER_RULES.md` 11장 또는 새 15장 추가
- **이점** : 본 P0 후보 A 의 근본 원인 (drift 채널 자체) 재발 방지
- **단점** : 운영자 행동 통제 — 운영자 동의 필요

### 권고
- **B + D 병행** : B 는 코드 안전망, D 는 운영 가드레일. 둘 다 작은 작업이라 1세션 처리 가능.
- 다만 RUNNER_RULES 4장 "한 번에 하나의 문제만" 원칙상 운영자가 1개를 명시 선택하는 게 정석.

---

## Files Forbidden To Change (다음 P0 후보 선택까지 유효)
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
**APPROVE (P0 후보 A 종결 박제) + NEEDS_HUMAN (다음 P0 선택)**

운영자 결정 기록 (누적):
- 08:37 KST : 직전 P0 종결, 후보 A/B/C 중 1개 선택 요청
- 08:41 KST : 후보 A 채택 → 실측 명령 발신
- 08:49 KST : 1차 실측 결과 박제, 후보 2개 그룹으로 좁힘
- 09:00 KST : 2차 실측 + 운영자 1줄 회신 → D1+D3 단정, P0 후보 A 종결

다음 세션 트리거:
- 운영자가 다음 P0 후보 (B / C / D) 중 1개 명시 선택
- 또는 새 hotfix 발생 시 그쪽 우선

---

## Next Handoff Rule
- 운영자 후보 선택 후 다음 세션에서 해당 후보 P0 진입 박제
- 후보 D (RUNNER_RULES 부칙) 채택 시 코드 변경 0, 문서만
- 후보 B 채택 시 mock_providers 1개 파일 + tests 1개 파일만
- 후보 C 채택 시 우선 read-only 점검만 (보호 영역)
