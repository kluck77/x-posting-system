# TASK_BOARD

이 문서는 **현재 단 1개의 문제** 만 전면에 둔다.
다른 모든 문제는 이 문제가 닫힐 때까지 대기한다.

---

## Updated At
2026-04-09 08:37 KST

## Updated By
Claude Code (claude/x-posting-ops-review-7hlxK)

## Current Stage
직전 P0 종결. **다음 P0 1개 선택 대기 중** (NEEDS_HUMAN).

## Current Priority
**미정** — 운영자가 아래 후보 중 1개 선택해야 진행

---

## Closed Issues (직전 P0 종결 기록)

### ✅ Reviewer JSON 파싱 실패 원인 분리 → H1 (코드 펜스) 확정
- 종결 일시 : 2026-04-09 08:37 KST
- 적용 패치 :
  - `9b5f830` cecd4ab 동등본 (관측 로그) — 36+/1-
  - `b62cc33` dd49fd3 동등본 (sanitize) — 39+/1-
- 결정적 근거 (server.log 4건 일관 패턴) :
  - sanitize 가 정확히 −12 chars 절감 (= ` \`\`\`json\n` + `\n\`\`\`` 합계 12자)
  - 4/4 케이스에서 sanitize 적용 → parsed 성공으로 이어짐
  - sanitize 후 parse 실패 0건
- 결론 :
  - **H1 (마크다운 코드 펜스 ` \`\`\`json … \`\`\` `) 확정**
  - H2 / H3 / H4 / H5 모두 본 데이터에선 미관찰
- 잔여 위험 (다음 P0 후보로 분리) :
  - 누적 `Claude Reviewer 오류` 15건 중 sanitize 패치 *이후* 발생 케이스 0건 여부 미확정
  - 운영자 권장 검증 : `grep -nE "Claude Reviewer 오류" /root/x-posting-system/server.log | tail -10`

---

## Confirmed Facts (현재 시점)

### 안정화 완료
- `/ingest` 파이프라인 정상
- provider 시그니처 phase-8α 호환
- 텔레그램 카드 전송 정상
- Reviewer JSON 파싱 (H1 케이스) 정상화 — sanitize 4/4 성공
- DraftWriter / Reviewer 응답 진단 로그 (Phase8α) 부착 완료

### 작업 브랜치 HEAD
- `b62cc33` feat(phase-8β): apply dd49fd3 equivalent — Reviewer JSON sanitize before parse
- 브랜치 : `claude/x-posting-ops-review-7hlxK`

### 서버 운영 라인
- 베이스 : `claude/premium-control-room-ui-LJFba @ 58f89b0`
- surgical 적용본 (origin/claude/x-posting-ops-review-7hlxK 기준) :
  - `app/providers/openai_provider.py` (963b626 본)
  - `app/providers/anthropic_provider.py` (b62cc33 본)
- 그 외 무변경

---

## Next P0 — 후보 (운영자 1개 선택 필요)

### 후보 A : 서버 anthropic_provider.py 출처 미상 변경 채널 식별 (★ 신규 ★)
- 발견 시점 : 2026-04-09 08:22 ~ 08:37 KST 직전 두 세션 모두
- 관찰된 사실 :
  - 본 세션에서 cecd4ab / dd49fd3 동등본을 surgical checkout 하기 *이전* 시점에
    이미 서버 server.log 에 `[Phase8α]` / `[Phase8β]` 로그가 박혀 있었음
  - 즉 두 surgical checkout 모두 결과적으로 no-op
  - GitHub 작업 브랜치에 박제되지 않은 surgical patch 가
    서버 anthropic_provider.py 에 들어오는 경로가 있다
- 영향 :
  - GitHub 가 단일 source of truth 라는 RUNNER_RULES 의 핵심 전제가 흔들림
  - drift 가 누적되면 다음 hotfix 시 conflict 나 회귀 위험
- 범위 :
  - 코드 수정 0
  - 서버에서 `git log -1 --format="%h %s" -- app/providers/anthropic_provider.py` /
    `stat -c '%y' app/providers/anthropic_provider.py` /
    `find /root/x-posting-system -name '*.bak*' -mtime -7` 정도 실측
  - HANDOFF_LOG 에 결과 박제만
- 추천 사유 : RUNNER_RULES 의 무결성 직결, 다른 P0 보다 우선

### 후보 B : `mock_providers.py` kwarg 미수신 (잠재 TypeError)
- 영향 : Anthropic 키 부재 시 fallback 으로 빠지면 `source_type` / `criteria_context`
  kwarg 를 못 받아 TypeError 가 다시 터질 수 있음
- 범위 : `app/providers/mock_providers.py` 1파일 (보호 영역 — 사전 승인 필요)
- 추천 사유 : 운영 라인은 키가 있어 바로 안 터지지만, 키 회전 / 장애 시 즉발 위험

### 후보 C : 로컬 `base.py` 와 서버 `base.py` 의 ReviewResult 필드 drift
- 영향 : 서버 본에는 `regeneration_hint`, `quality_flags` 가 있고 로컬엔 없음
- 범위 : `app/providers/base.py` (보호 영역 — 사전 승인 필요)
- 추천 사유 : 다음 reviewer 강화 패치를 막는 잠재 장애물

---

## Why This Is Next
- 직전 P0 종결 후 가장 큰 운영 위험은 **GitHub vs 서버 drift** 자체이다 (후보 A).
- 후보 A 를 먼저 깔끔히 정리해야 후보 B/C 의 surgical patch 도 안전하다.
- RUNNER_RULES 3장 "GitHub 의 최신본이 기준이다" 의 직접 침해 사례.

---

## Minimal Scope
운영자 결정 전까지 코드 수정 0. 후보 A 는 그 자체가 코드 수정 0 (실측만).

---

## Exact Files To Change
운영자 결정 전 : 없음

후보별 :
- A : 코드 변경 0 (서버 실측만 + HANDOFF_LOG 박제)
- B : `app/providers/mock_providers.py` 1파일 — 운영자 사전 승인 필요
- C : `app/providers/base.py` 1파일 — 운영자 사전 승인 필요

---

## Files Forbidden To Change
- `app/orchestrator.py`
- `app/api/admin.py`
- `app/services/*` 전체
- `app/models/*` 전체
- `dashboard/` 전체
- `.env`
- `main` 브랜치
- prompt / model / max_tokens / config
- `app/providers/base.py` (후보 C 선택 시에만 1파일 한정 사전 승인)
- `app/providers/mock_providers.py` (후보 B 선택 시에만 1파일 한정 사전 승인)

---

## Validation Steps
운영자 결정 전 : 해당 없음

후보 A 가 선택되면 (코드 수정 0, 운영자 복붙 명령 후보) :
```
cd /root/x-posting-system
git log -1 --format="%h %ci %s" -- app/providers/anthropic_provider.py
stat -c '%y' app/providers/anthropic_provider.py
find /root/x-posting-system -name '*.bak*' -mtime -7 2>/dev/null
ls -la /root/x-posting-system/app/providers/anthropic_provider.py
sha256sum /root/x-posting-system/app/providers/anthropic_provider.py
git status -s app/providers/anthropic_provider.py
git diff origin/claude/x-posting-ops-review-7hlxK -- app/providers/anthropic_provider.py | head -40
```

---

## Recommendation
**NEEDS_HUMAN** — 후보 A / B / C 중 1개 선택

추천 우선순위 : **A → B → C**
- A : drift 진단 (코드 수정 0, 가장 빠르고 가장 위험)
- B : fallback path 잠재 TypeError (운영 시 즉발 위험 낮음)
- C : 향후 reviewer 강화 차단 요소 (장기 부담)

---

## Next Handoff Rule
- 운영자가 후보 A/B/C 중 1개를 선택하면 `HANDOFF_LOG.md` 최상단에 결정 근거와 함께 새 항목 추가
- 본 TASK_BOARD 의 Current Issue / Next P0 섹션을 선택된 후보로 갱신
- 다음 세션은 선택된 후보 1개에만 집중
