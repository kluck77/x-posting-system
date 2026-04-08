# TASK_BOARD

이 문서는 **현재 단 1개의 문제** 만 전면에 둔다.
다른 모든 문제는 이 문제가 닫힐 때까지 대기한다.

---

## Updated At
2026-04-09 08:32 KST

## Updated By
Claude Code (claude/x-posting-ops-review-7hlxK)

## Current Stage
sanitize 적용 완료. **다음 Reviewer 호출 1회 재검증 대기 중**.

## Current Priority
P0 — Reviewer 응답 sanitize 효과 실측 확인 (Phase8β 로그로 H1/H2 확정 또는 추가 가설 분기)

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

### 직전 세션 (관측 패치) 커밋
- `9b5f830` cecd4ab 동등본 수동 반영 — `app/providers/anthropic_provider.py` 1파일, 36+/1-
- 진단 로그 5종 추가, 동작 변경 0

### 직전 세션 관측 결과 (서버 server.log 실측)
- 실패 케이스 1건: `response http=200 content_len=862` 직후 `parsed` 줄 없음
- 성공 케이스 4건: `response http=200 content_len=760~933` → `parsed risk=medium`
- 즉 비-empty 응답인데 json.loads 실패 → **H3 (빈 응답) 배제 확정**
- 강한 후보로 H1 (코드 펜스) / H2 (preamble) 만 남음
- raw_content_preview 는 DEBUG 라 INFO 로그에 안 잡힘 → preview 없이 sanitize 로 우회

### 본 세션 (sanitize 패치) 커밋
- `dd49fd3` 동등본 수동 반영 — `app/providers/anthropic_provider.py` 1파일, 39+/1-
- `_sanitize_json_content()` top-level helper 신규
- review_and_refine 의 `json.loads` 직전에 sanitize 적용 + 효과 발생 시 `[Phase8β]` 1줄 INFO 로그
- 옵션 B 채택 — H1/H2 동시 해소

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
sanitize 패치 적용 완료. 다음 단계는 **서버 적용 + Reviewer 1회 재검증**. 코드 수정 0.

원인 후보 (직전 세션 관측 후 갱신):
- **H1** 마크다운 코드 펜스 prefix (\`\`\`json …) — sanitize 가 처리. 효과 시 `[Phase8β]` 로그로 확정.
- **H2** 설명 텍스트 preamble ("Here is the review: …") — sanitize 가 처리. 효과 시 `[Phase8β]` 로그로 확정.
- **~~H3~~** ~~빈 문자열~~ — **배제 (content_len=862 실측)**
- **H4** BOM/공백 prefix — sanitize 가 처리. (낮은 가능성)
- **H5** JSON 미완 — 여전히 매우 낮음

배제된 가설:
- **R1~R5** (직전 세션과 동일)
- **H3** 신규 배제 (직전 세션 관측 결과)

확정 시나리오 (다음 Reviewer 호출 1회 후):
- `[Phase8β] sanitize applied` + `parsed risk=...` → H1/H2 확정, sanitize 효과적, 종결
- `parsed risk=...` 만 (sanitize 미적용) → 그 응답은 원래 clean. 다음 호출 대기.
- `sanitize applied` + `Claude Reviewer 오류:` → 새 가설 필요 (sanitize 가 H1/H2 외 케이스를 못 잡음)
- 둘 다 없음 + `Claude Reviewer 오류:` → preview 캡처 (DEBUG 승격) 필요

---

## Exact Files To Change
이번 단계: **없음** (수정 0). sanitize 패치는 이미 본 세션에서 반영됨.

다음 단계 (재검증 후) 분기:
- sanitize 효과 확인 → 본 P0 종결, 다음 P0 후보로 교체 (mock_providers kwarg / base.py drift 등)
- sanitize 효과 미확인 → DEBUG 승격 또는 새 가설 → 1파일 후속 패치

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
이번 단계 (sanitize 패치 본 커밋에 반영됨):
- 로컬 `python3 -m py_compile app/providers/anthropic_provider.py` → OK
- 로컬 AST 시그니처 실측 → 3개 메서드 무변경, helper 1개 신규, 호출 1회
- 로컬 sanitize 7케이스 실측 → 전부 OK (clean 은 byte-identical pass-through)
- diff stat: `1 file changed, 39 insertions(+), 1 deletion(-)` — dd49fd3 와 동일

다음 단계 (서버 적용 + 재검증):
1. 서버에서 1파일 surgical checkout
   ```
   cd /root/x-posting-system
   git fetch origin claude/x-posting-ops-review-7hlxK
   git checkout origin/claude/x-posting-ops-review-7hlxK -- app/providers/anthropic_provider.py
   ```
2. venv import smoke
   ```
   /root/x-posting-system/venv/bin/python -c "from app.providers.anthropic_provider import AnthropicReviewer, _sanitize_json_content; import inspect; print(inspect.signature(AnthropicReviewer.review_and_refine)); print(_sanitize_json_content('```json\n{\"a\":1}\n```'))"
   ```
3. `systemctl restart xdashboard.service && systemctl is-active xdashboard.service`
4. 다음 Reviewer 호출 1회 발생까지 대기 (`/ingest` 실측)
5. `grep -nE "Phase8[αβ].*Reviewer" /root/x-posting-system/server.log | tail -30`
6. `[Phase8β] sanitize applied` + `parsed risk=...` 동시 출현 시 종결

---

## Recommendation
**APPROVE** — 옵션 B 채택 완료. 본 세션에서 sanitize 패치 반영 끝.

운영자 결정 기록 (누적):
- 직전 세션: (1) 관측만 채택 → cecd4ab 동등본 반영 → 서버 실측 → H3 배제
- 본 세션: (B) sanitize 채택 → dd49fd3 동등본 반영 → H1/H2 동시 해소 시도

다음 세션 트리거:
- 서버 surgical checkout + 재시작 + Reviewer 호출 1회 발생 후
- `[Phase8β] sanitize applied` + `parsed risk=...` 동시 잡히면 본 P0 종결
- 종결 시 본 문서를 후보 1순위(`mock_providers.py` kwarg 미수신)로 교체

---

## Next Handoff Rule
- 운영자가 (1)/(2)/(3) 중 선택을 결정하면 `HANDOFF_LOG.md` 최상단에 결정 근거와 함께 새 항목을 추가한다.
- 다음 세션은 본 TASK_BOARD 의 Current Issue 가 닫힐 때까지 다른 문제로 넘어가지 않는다.
- Current Issue 가 닫히면 본 문서를 다음 후보 1개로 교체한다.
  - 후보 1순위: `mock_providers.py` kwarg 미수신 (서버 fallback 시 잠재 TypeError)
  - 후보 2순위: 로컬 `base.py` 와 서버 `base.py` 의 ReviewResult 필드 drift
