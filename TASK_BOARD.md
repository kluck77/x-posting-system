# TASK_BOARD

이 문서는 **현재 단 1개의 문제** 만 전면에 둔다.
다른 모든 문제는 이 문제가 닫힐 때까지 대기한다.

---

## Updated At
2026-04-09 08:22 KST

## Updated By
Claude Code (claude/x-posting-ops-review-7hlxK)

## Current Stage
관측 패치 적용 완료. **다음 Reviewer 호출 1회 대기 중** (preview 캡처 단계).

## Current Priority
P0 — Reviewer JSON 파싱 실패 원인 분리 (preview 캡처로 H1~H5 확정)

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

### 본 세션 (관측 패치) 커밋
- `cecd4ab` 동등본 수동 반영 — `app/providers/anthropic_provider.py` 1파일, 36+/1-
- 진단 로그 5종 추가, 동작 변경 0
- 옵션 (1) 채택 — sanitize 미반영, dd49fd3 미반영

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
관측 패치 적용 완료. 다음 단계는 **수집 + 분기 확정**. 코드 수정 0.

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
- Reviewer 응답 raw_content 첫 200 chars 의 1회 캡처
- **관측 수단 부착 완료** (`[Phase8α][Claude Reviewer] raw_content_preview=...` DEBUG 로그)
- 다음 Reviewer 호출 1회만 발생하면 분기 확정 가능

---

## Exact Files To Change
이번 단계: **없음** (수정 0). 관측 패치는 이미 본 세션에서 반영됨.

다음 단계 (preview 확보 후) 후보:
- preview 첫 글자가 \`\`\` 또는 ` 면 → H1 (코드 펜스) 확정 → sanitize 패치
- preview 첫 글자가 알파벳/한글 면 → H2 (preamble) 확정 → strip 또는 prompt 보강
- preview 가 빈 문자열이면 → H3 (정책 거부 / max_tokens) 확정 → max_tokens 조정 검토
- preview 첫 글자가 BOM/공백 면 → H4 확정 → strip
- 어떤 분기든 수정은 `app/providers/anthropic_provider.py` **1파일** 만

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
이번 단계 (관측 패치 본 커밋에 반영됨):
- 로컬 `python3 -m py_compile app/providers/anthropic_provider.py` → OK
- 로컬 AST 시그니처 실측 → 무변경 확인 완료
- diff stat: `1 file changed, 36 insertions(+), 1 deletion(-)` — cecd4ab 와 동일

다음 단계 (서버 적용 + preview 캡처):
1. 서버에서 1파일 surgical checkout
   ```
   cd /root/x-posting-system
   git fetch origin claude/x-posting-ops-review-7hlxK
   git checkout origin/claude/x-posting-ops-review-7hlxK -- app/providers/anthropic_provider.py
   ```
2. venv import smoke
   ```
   /root/x-posting-system/venv/bin/python -c "from app.providers.anthropic_provider import AnthropicReviewer; import inspect; print(inspect.signature(AnthropicReviewer.review_and_refine))"
   ```
3. `systemctl restart xdashboard.service && systemctl is-active xdashboard.service`
4. 로그 레벨 점검: `raw_content_preview` 는 DEBUG. 운영 로그가 INFO 라면 임시로 DEBUG 승격 필요
5. 다음 Reviewer 호출 1회 발생까지 대기 (`/ingest` 실측)
6. `grep -nE "Phase8α.*Reviewer" /root/x-posting-system/server.log | tail -20`
7. `raw_content_preview` 첫 글자로 H1~H5 분기 확정 → 다음 세션 fix 결정

---

## Recommendation
**APPROVE** — 옵션 (1) 채택 완료. 본 세션에서 관측 패치 반영 끝.

운영자 결정 기록:
- 채택: **(1) 가장 안전 — 관측만**
- 거절: (2) sanitize 동반은 prior evidence 인용 단계가 섞여 단계 분리 원칙 위반
- 거절: (3) 카드 품질 저하 만성화 유지

다음 세션 트리거:
- 서버 surgical checkout + 재시작 + Reviewer 호출 1회 발생 후
- preview 가 server.log 에 잡히면 H1~H5 중 하나 확정
- 그 분기에 맞는 최소 fix 1파일을 다음 세션에서 적용

---

## Next Handoff Rule
- 운영자가 (1)/(2)/(3) 중 선택을 결정하면 `HANDOFF_LOG.md` 최상단에 결정 근거와 함께 새 항목을 추가한다.
- 다음 세션은 본 TASK_BOARD 의 Current Issue 가 닫힐 때까지 다른 문제로 넘어가지 않는다.
- Current Issue 가 닫히면 본 문서를 다음 후보 1개로 교체한다.
  - 후보 1순위: `mock_providers.py` kwarg 미수신 (서버 fallback 시 잠재 TypeError)
  - 후보 2순위: 로컬 `base.py` 와 서버 `base.py` 의 ReviewResult 필드 drift
