# TASK_BOARD

이 문서는 **현재 단 1개의 문제** 만 전면에 둔다.
다른 모든 문제는 이 문제가 닫힐 때까지 대기한다.

---

## Updated At
2026-04-09 09:06 KST

## Updated By
Claude Code (claude/x-posting-ops-review-7hlxK)

## Current Stage
**P0 후보 D 종결. 후보 B 진입 (mock_providers kwarg 시그니처 정합).**

## Current Priority
P0 — **mock_providers kwarg 시그니처 phase-8α 정합 검증/보강** (후보 B)

---

## Closed Issues (직전 P0 종결 기록 — 누적식)

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

### 작업 브랜치 HEAD (GitHub 기준선)
- 직전 docs HEAD : `031e1c9` (P0 후보 A 종결 박제)
- 직전 코드 HEAD : `b62cc33` (anthropic_provider.py 39+/1- sanitize)
- 현재 시점 서버 == GitHub `b62cc33` byte-identical (1차 실측 확인)
- 브랜치 : `claude/x-posting-ops-review-7hlxK`

---

## Current Issue
**mock_providers kwarg 시그니처 phase-8α 정합 검증/보강 (후보 B)**

목표 : `app/providers/mock_providers.py` 의 mock 5종이 phase-8α 이후 시그니처 (`criteria_context` kwarg) 와 100% 정합한지 검증 + 누락 시 보강 + pytest 통과.

### 진입 근거
- phase-8α 진단 로그 + sanitize 패치 적용 후, 운영 라인 (Anthropic / OpenAI) 시그니처는 검증 완료
- mock_providers 는 키 부재 시 fallback / 로컬 dev / pytest 에서만 사용
- 시그니처 누락 시 fallback 호출에서 TypeError 잠복 가능 (운영 라인 외 환경에서 깨짐)
- 본 P0 는 코드 변경 최소화 + 테스트 통과 중심

---

## Minimal Scope
- `app/providers/mock_providers.py` 시그니처 점검 및 누락 시 1개 파일 패치
- `tests/test_providers.py` 가 이미 통과하는지 확인 + 필요 시 보조 테스트 1~2개 추가만
- AI 호출 0, 외부 의존 0

---

## Exact Files To Change (점검 결과에 따라 0~2개)
- `app/providers/mock_providers.py` (필요 시)
- `tests/test_providers.py` (필요 시)

---

## Files Forbidden To Change
- `app/orchestrator.py`
- `app/api/admin.py`
- `app/providers/base.py` (read-only 참조만)
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

### 본 P0 검증 (로컬, 5분 이내)
```
cd /home/user/x-posting-system
python3 -m py_compile app/providers/mock_providers.py
python3 -m pytest tests/test_providers.py -v
```

### 시그니처 비교 (read-only)
- `BaseReviewer.review_and_refine()` (base.py) vs
  `MockReviewer.review_and_refine()` vs
  `AnthropicReviewer.review_and_refine()` 의 인자 목록 동일성 확인
- `BaseDraftWriter.generate_draft()` vs `MockDraftWriter.generate_draft()` vs
  `OpenAIDraftWriter.generate_draft()` 동일성 확인

---

## Recommendation
**APPROVE (B 진입)** — 점검 단계는 read-only, 패치 단계는 1개 파일 한정.

---

## Next Handoff Rule
- 점검 결과 시그니처 정합 → 코드 변경 0, B 즉시 종결
- 점검 결과 시그니처 누락 → mock_providers.py 1개 파일 minimal patch + pytest 통과 → B 종결
- B 종결 후 다음 P0 운영자 선택 대기 (후보 C 또는 새 hotfix)
