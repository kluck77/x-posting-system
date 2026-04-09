# RUNNER_RULES

이 문서는 x-posting-system 운영의 절대 규칙이다.
세션이 바뀌어도 이 문서가 기준이다. 채팅방 메모리는 기준이 아니다.

---

## 1. 목적

- 채팅 복붙으로 흔들리던 기준선을 GitHub 문서로 고정한다.
- 누구든 처음 이 레포를 열면 현재 상태와 다음 액션을 5분 안에 파악할 수 있게 한다.
- 서버/로컬 drift 와 surgical patch 의 반복 손실을 막는다.

## 2. 역할 고정

- **운영자** : 사람. 의사결정 + 서버 명령 실행 + 텔레그램 카드 운영.
- **GPT (머리)** : GitHub 문서를 읽고 판정 / 다음 지시를 작성. 코드 직접 수정 안 함.
- **Claude Code (손)** : GitHub 문서를 생성·갱신하고 실제 코드 작업 수행. 추측 금지.
- 운영자는 중간 전달자 역할만 한다.

## 3. 최신 기준선 원칙

- **GitHub 의 최신본이 기준이다.** 채팅 메모리, 운영자 기억, 로컬 워크트리는 기준이 아니다.
- 서버 운영 라인과 로컬 작업 브랜치는 항상 다를 수 있다고 전제한다.
- 모든 작업은 다음 순서로만 진행:
  1. 기준선 박제 (서버 HEAD / 작업 브랜치 HEAD 양쪽 commit sha 기록)
  2. 로컬 통합 검증
  3. 파일 선택 반영
- 서버 전체 pull / 전체 재배포 금지.

## 4. 작업 방식

- 한 번에 하나의 문제만 다룬다. 동시에 두 문제 섞지 않는다.
- 작은 승리부터 쌓는다. 완벽주의보다 실전 안정성이 우선이다.
- 추측 금지. 모르면 "실측 필요"로 적는다.
- broad refactor 금지. 덧붙이기식 패치 금지.
- 관련 없는 파일 수정 금지.
- 분석 단계와 수정 단계를 명확히 분리한다.
- 에러가 났을 때 코드를 먼저 고치지 않는다. **어느 단계에서 막히는지 먼저 확정**한다.
- TEMP 패치와 영구 패치는 절대 섞지 않는다. TEMP 는 본선 HEAD 에 반영 금지.

## 5. 영구 보호 영역 (사전 승인 없이 절대 수정 금지)

- `app/orchestrator.py`
- `app/api/admin.py`
- `app/providers/base.py`
- `app/services/telegram_service.py`
- `app/services/draft_service.py`
- `app/services/source_service.py`
- `app/services/candidate_filter.py`
- `app/models/content.py`
- `dashboard/` 전체
- `.env`
- `main` 브랜치
- approval flow 의미 변경 일체
- prompt / max_tokens / env / config 임의 변경 일체

## 6. 서버 반영 원칙

- 전체 pull 금지. 개별 파일 선택 적용만 허용.
- 서버 적용 전 검증 / 서버 적용 후 검증을 분리해서 제시.
- 어떤 파일이 정확히 교체되는지 명시 (commit sha + file path).
- destructive 명령 (kill, rm, reset, force push, git clean -fd 등) 은 운영자 승인 전 금지.
- 검증 명령에는 venv python 을 명시한다 (`/root/x-posting-system/venv/bin/python`).
- 시스템 python 으로 import smoke 돌리지 말 것.

## 7. 분석/수정 기본 순서

모든 작업은 아래 7단계 순서로만 진행한다.

1. **Confirmed Facts** : 코드/로그 실측으로 확인된 사실
2. **Root Cause or Core Judgment** : 단정할 수 있을 때만 단정. 아니면 후보로 표시.
3. **Minimal Fix Scope** : 가장 작은 수정 범위
4. **Exact Files To Change** : 정확한 파일 경로
5. **Files Forbidden To Change** : 보호 영역 명시
6. **Validation Steps** : 5분 안에 복붙 가능한 검증 명령
7. **Recommendation** : APPROVE / NEEDS_HUMAN / REJECT

## 8. Preflight Sweep 규격 (모든 코드 수정 후 필수)

다음 7항목을 반드시 포함해서 보고한다.

- **Changed Files** : 변경된 파일 경로
- **Syntax Check Result** : `python3 -m py_compile <files>` 결과
- **Signature Compatibility Check Result** : 시그니처 호환성 (호출부 grep 포함)
- **Test Result** : pytest 결과 또는 실행 불가 사유
- **Runtime Risk Remaining** : 남은 런타임 위험
- **Server Apply Risk** : 서버 적용 시 위험
- **Recommendation** : APPROVE / NEEDS_HUMAN / REJECT

## 9. Claude Code 출력 형식

- 응답은 한국어로만.
- 운영자에게 주는 최종 답변은 코드블록에 담는다.
- 장황한 설명 금지. 칭찬/공감 남발 금지.
- 결정 / 사실 / 위험 / 다음 액션 중심.
- 복붙 가능한 명령어를 항상 제공.
- 확실하지 않으면 "실측 필요" 라고 적는다.

## 10. 문서 갱신 규칙

- **GitHub 최신본이 기준이다.** 로컬 메모리는 기준 아님.
- 코드 변경 작업이 끝날 때마다 `HANDOFF_LOG.md` 최상단에 새 항목 추가.
- 새 문제를 잡기 시작할 때 `TASK_BOARD.md` 의 Current Issue 1개를 교체.
- `RUNNER_RULES.md` 는 운영 원칙이 바뀔 때만 갱신. 잦은 수정 금지.
- 각 문서는 KST 타임스탬프를 명시.
- 작업 중인 문제는 항상 1개만 전면에 둔다.

## 11. 날짜/시간 기록 규칙

- 표기 형식: `YYYY-MM-DD HH:MM KST`
- 명령으로 얻기: `TZ=Asia/Seoul date '+%Y-%m-%d %H:%M KST'`
- 서버 로그는 UTC 일 수 있음 → 인용 시 원본 그대로 + KST 환산 병기.

## 12. 현재 프로젝트 방향

- 네이버/RSS API : 많이 모으는 역할
- AI : 고른 것만 깊게 읽는 역할
- 비용 통제 핵심은 모델 선택보다 AI 호출 게이트
- 대시보드 상시 감시 구조 지양
- 텔레그램 중심 승인/보류 구조 선호
- 재료 선별 엔진 먼저, 글 품질 향상은 그 다음
- 한국 내 인기 뉴스 ≠ 해외 독자 관심 뉴스 — 분리 필터 필요
- 목표는 "한국에서 뜨는 뉴스" 가 아니라 "해외 독자가 한국을 이해하게 만드는 뉴스"

## 13. AI 역할 고정

- **DraftWriter** : OpenAI (gpt-4o-mini)
- **Reviewer** : Anthropic (Claude Sonnet 4)
- **Researcher / TrendHunter / FactChecker** : v1 은 Mock
- Grok 은 단독 게이트가 아니라 보조 점수 또는 후속 단계에서 활용
- mock_providers 는 키 부재 시 fallback. 운영 라인에서는 사용 안 함.

## 14. 현재 운영 핵심

- **1차 필터** : AI 0 비용 휴리스틱
- **2차 점수** : 휴리스틱 점수
- **3차 컷라인** : 컷라인 넘는 것만 초안 생성
- 둥근 컷라인과 명확한 상태값 선호 (`candidate_status`, `candidate_score` 같은 명시적 컬럼명)
- 더미 점수로 정밀한 척하는 구조 금지
- Reviewer 단계는 게이트 + 안전망 + 최종 다듬기 역할

## 15. Drift 방지 부칙 — 운영자 직접 작업 알림 의무

> 본 부칙은 2026-04-09 P0 후보 A 종결 (D1+D3 결합 채널 단정) 의 회고로 추가됨.
> 원인 : 운영자 / 다른 Claude Code 세션이 임시 브랜치 + .bak + surgical checkout 를 본 세션에 알리지 않고 수행 → GitHub 기준선과 서버 working tree drift 누적.

### 15.1 운영자 사전 알림 의무 (5개 행위)

운영자는 아래 5개 행위 중 하나라도 수행하면 **수행 직후 1회 이내** 본 채팅 세션에 1줄로 알린다.

1. 서버에서 `git checkout <ref> -- <file>` (surgical checkout) 실행
2. 서버에서 임시 브랜치 (`temp/...`, `wip/...`, 그 외 비표준 브랜치) 생성 / checkout
3. 서버에서 `.bak` 파일 생성 / 복원 / 삭제
4. 본 세션과 다른 Claude Code 세션을 동일 서버에 동시 가동
5. 운영자 직접 (vim / nano / scp / 파일 매니저) 보호 영역 파일 수정

알림 양식 (1줄 권장) :

```
[운영자작업] <행위> <파일/대상> @<UTC시각>
예: [운영자작업] surgical checkout app/providers/anthropic_provider.py @2026-04-08 04:24
```

### 15.2 Claude Code 측 의무

- 코드 변경 작업 진입 시 운영자에게 "직전 24h 내 위 5개 행위 수행 여부" 1줄 확인 요청.
- 응답 "있음" 일 때 사전에 서버 sha256 + git status + git reflog 1줄 실측 후 작업 시작.
- 응답 미수신 상태로 보호 영역 / 운영 라인 파일 surgical checkout 진행 금지.

### 15.3 위반 시 처리

- 본 부칙 위반으로 drift 발생 시 다음 hotfix 는 즉시 STOP. 먼저 drift 채널 식별 후 재진입.
- 위반은 비난 대상이 아니라 **재발 방지 회고 대상**. 이력은 `HANDOFF_LOG.md` 에 박제.

### 15.4 본 부칙의 한계

- 운영자 행동을 강제 차단할 기술적 수단은 없음 (서버 권한은 운영자 보유).
- 본 부칙은 **운영 약속** 이며 신뢰 기반 운영.
- 자동화 가드레일 (pre-commit hook / CI 검증 / 서버 sha256 watch) 은 별 P0 분기로만 도입.

---

이 문서를 어긴 작업은 즉시 STOP. 다시 이 문서로 돌아와서 시작한다.
