# TASK_BOARD

이 문서는 **현재 단 1개의 문제** 만 전면에 둔다.
다른 모든 문제는 이 문제가 닫힐 때까지 대기한다.

---

## Updated At
2026-04-09 08:10 KST

## Updated By
Claude Code (claude/x-posting-ops-review-7hlxK)

## Current Stage
실측 / 원인 분리 단계 (수정 단계 아님)

## Current Priority
P0 — Reviewer JSON 파싱 실패 원인 분리

---

## Confirmed Facts (직전 hotfix 종결 기준)

### 해결 완료
- `/ingest` 죽던 문제 해결
- `NoneType.strip` 해결 (draft_service 가드)
- provider 시그니처 불일치 해결
  - `OpenAIDraftWriter.generate_draft()` 가 `source_type` 수신
  - `AnthropicDraftWriter.generate_draft()` 가 `source_type`, `criteria_context` 수신
  - `AnthropicReviewer.review_and_refine()` 가 `criteria_context` 수신
- 텔레그램 승인 카드 전송 복구
- 실측 검증
  - `/ingest` 응답: `success=true`, `draft_id=17`, `telegram_sent=true`
  - 서버 재시작 후 `xdashboard.service` active
  - 새 TypeError 0건

### 직전 hotfix 커밋
- `963b626` fix(providers): restore phase-8α kwargs + keep null-guard
- `dc141f7` session(2026-04-08): provider phase-8α hotfix 종결
- 브랜치: `claude/x-posting-ops-review-7hlxK`

---

## Current Issue
**Reviewer JSON 파싱 실패 원인 분리**

증상:
```
[WARNING] Reviewer 실패, DraftWriter 결과 직접 사용:
Claude Reviewer 오류: Expecting value: line 1 column 1 (char 0)
```

발생 위치 (코드 실측):
- 파일: `app/providers/anthropic_provider.py`
- 라인: 167
- 코드: `data = json.loads(content)`
- 예외: `json.decoder.JSONDecodeError`

발생 빈도:
- 만성. 04-07 ~ 04-08 server.log 에 7회 이상 반복.
- 본 hotfix 와 시간선상 무관 — 그 이전부터 발생.

영향:
- 파이프라인 죽지 않음 (orchestrator fallback 작동)
- 카드 자체는 항상 전송됨
- 단, Reviewer 가 다듬은 hook/body 가 아니라 DraftWriter 원본이 카드에 노출
- risk_level 이 항상 medium 으로 강제 (`Fallback: reviewer unavailable`)
- 운영 품질 저하 만성화

---

## Why This Is Next
1. provider 시그니처 hotfix 가 끝나서 파이프라인 자체는 살아있다.
2. 다음으로 운영 품질을 떨어뜨리는 가장 큰 단일 요인이 Reviewer fallback 만성화다.
3. Reviewer 가 정상화돼야 5-Criteria 점수, 위험 등급, 다듬어진 hook/body 가 카드에 정상 노출된다.
4. mock_providers / base.py drift 등 다른 후보보다 운영 영향이 명확히 더 크다.

---

## Minimal Scope
이번 단계는 **수정 0**. 무수정 원인 분리만 한다.

원인 후보 (코드 실측 + git 히스토리 기반):
- **H1** 마크다운 코드 펜스 prefix (\`\`\`json …) — 가능성 높음
- **H2** 설명 텍스트 preamble ("Here is the review: …") — 가능성 중간
- **H3** 빈 문자열 (정책 거부 / max_tokens 컷오프) — 가능성 중간
- **H4** BOM/공백 prefix — 가능성 낮음
- **H5** JSON 미완 (`}` 누락) — 가능성 매우 낮음 (col 0 char 0 와 불일치)

배제된 가설 (이미 코드 실측으로 제거):
- **R1** mock_providers 가 reviewer 경로에 섞여 있음 → 라우팅상 불가
- **R2** content 필드 선택 오류 → KeyError 가 먼저 났을 것
- **R3** 전처리 함수가 payload 를 비움 → L166-L167 사이 코드 0줄
- **R4** 다중 reviewer 동시 실행 → 클래스 1개뿐
- **R5** 본 hotfix 가 원인 → 시간선상 무관

확정에 필요한 단 1가지:
- Reviewer 응답 raw_content 첫 200~300 chars 의 1회 캡처
- 현재 코드에는 해당 로그 0줄 → 관측 수단 없음

---

## Exact Files To Change
이번 단계: **없음** (수정 0)

다음 단계 (관측 패치 적용 시) 후보:
- `app/providers/anthropic_provider.py` (1파일)
  - 옵션 A: `cecd4ab` cherry-pick — 진단 로그만
  - 옵션 B: `cecd4ab` + `dd49fd3` cherry-pick — 진단 로그 + sanitize
- 두 옵션 모두 1파일, 동작 무변경 (sanitize 는 clean 입력에 pass-through)

---

## Files Forbidden To Change
- `app/orchestrator.py`
- `app/api/admin.py`
- `app/providers/base.py`
- `app/providers/mock_providers.py`
- `app/providers/ai_provider.py`
- `app/providers/openai_provider.py`
- `app/services/*` 전체
- `app/models/*` 전체
- `dashboard/` 전체
- `.env`
- `main` 브랜치
- prompt / max_tokens / config

---

## Validation Steps
이번 단계 (무수정): preflight 불필요

다음 단계 (관측 패치 적용 시):
1. `python3 -m py_compile app/providers/anthropic_provider.py`
2. venv import smoke
   ```
   /root/x-posting-system/venv/bin/python -c "from app.providers.anthropic_provider import AnthropicReviewer; import inspect; print(inspect.signature(AnthropicReviewer.review_and_refine))"
   ```
3. `systemctl restart xdashboard.service && systemctl is-active xdashboard.service`
4. 다음 Reviewer 호출 1회 발생까지 대기
5. `grep -nE "Phase8α.*Reviewer.*raw_content_preview" /root/x-posting-system/server.log | tail -5`
6. preview 첫 글자로 H1~H5 분기 확정

---

## Recommendation
**NEEDS_HUMAN**

운영자가 다음 3가지 중 1개를 선택해야 다음 세션이 진행된다.

- **(1) 가장 안전 — 관측만**
  `cecd4ab` 1커밋 cherry-pick → 진단 로그 5줄 추가 → 다음 호출 1회로 H1~H5 확정 → 그 다음 세션에서 fix.
  수정 1파일, 동작 변경 0.

- **(2) 한 번에 끝내기**
  `cecd4ab` + `dd49fd3` cherry-pick → 관측 + F2(코드 펜스/preamble) 자동 해소 동시 적용.
  수정 1파일, sanitize 는 clean 입력에 pass-through.
  단, prior evidence 인용 단계가 1개 섞임.

- **(3) 유지**
  현재 fallback 으로 운영은 굴러간다. 단, 카드 품질 저하 만성화.

---

## Next Handoff Rule
- 운영자가 (1)/(2)/(3) 중 선택을 결정하면 `HANDOFF_LOG.md` 최상단에 결정 근거와 함께 새 항목을 추가한다.
- 다음 세션은 본 TASK_BOARD 의 Current Issue 가 닫힐 때까지 다른 문제로 넘어가지 않는다.
- Current Issue 가 닫히면 본 문서를 다음 후보 1개로 교체한다.
  - 후보 1순위: `mock_providers.py` kwarg 미수신 (서버 fallback 시 잠재 TypeError)
  - 후보 2순위: 로컬 `base.py` 와 서버 `base.py` 의 ReviewResult 필드 drift
