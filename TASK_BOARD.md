# TASK_BOARD

이 문서는 **현재 단 1개의 문제** 만 전면에 둔다.
다른 모든 문제는 이 문제가 닫힐 때까지 대기한다.

---

## Updated At
2026-04-09 08:41 KST

## Updated By
Claude Code (claude/x-posting-ops-review-7hlxK)

## Current Stage
실측 명령 발신 완료. **운영자 서버 출력 수신 대기** (코드 변경 0).

## Current Priority
P0 — **서버 anthropic_provider.py 출처 미상 변경 채널 식별** (후보 A)

---

## Closed Issues (직전 P0 종결 기록 — 누적식)

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

### 작업 브랜치 HEAD (GitHub 기준선)
- `049e25b` docs(ops): close P0 (Reviewer JSON parse) — H1 confirmed via server log
- 직전 코드 HEAD : `b62cc33` (anthropic_provider.py 39+/1- sanitize)
- 브랜치 : `claude/x-posting-ops-review-7hlxK`

### 본 P0 의 결정적 정황 (직전 두 세션 누적)
- 2026-04-09 08:22 KST 세션 (cecd4ab 동등본 적용) :
  - surgical checkout 적용 *이전* (2026-04-08 05:37 ~ 11:12 UTC) 의 server.log 에
    이미 `[Phase8α]` 로그 다수 존재
- 2026-04-09 08:32 KST 세션 (dd49fd3 동등본 적용) :
  - 동일 패턴 — surgical checkout 적용 이전 시점에 이미 `[Phase8β]` 로그 4건 존재
- → GitHub 작업 브랜치를 **거치지 않은** patch 채널이 실재한다는 강한 정황
- → RUNNER_RULES 3장 "GitHub 의 최신본이 기준이다" 의 직접 침해

---

## Current Issue
**서버 anthropic_provider.py 출처 미상 변경 채널 식별 (후보 A)**

목표 : drift 채널을 후보 2개 이하로 좁힌다.
이번 단계 수정 : 0 (실측만)

### Drift 채널 가설 (실측 결과로 좁힐 후보)
- **D1** : 운영자 본인이 다른 브랜치에서 직접 surgical checkout
  - 검증 : `git log -1 --format='%h %ci %s' -- app/providers/anthropic_provider.py`
  - 확정 신호 : commit sha 가 `cecd4ab` / `dd49fd3` / 그 동등본을 가리키거나 작업 브랜치 외 sha
- **D2** : 다른 Claude Code 세션이 동일 서버에 surgical checkout
  - 검증 : 동일 git log + 운영자 기억 confirm
- **D3** : `.bak` / stash 기반 수동 복원
  - 검증 : `find ... '*.bak*' -mtime -7`
- **D4** : 파일 매니저 / IDE / scp 직접 업로드
  - 검증 : mtime + git status -s + sha256sum 비교
- **D5** : 자동화 deploy hook (cron / systemd timer / git pull)
  - 검증 : 본 세션 명령에 미포함 — 후속 분기에서 cron/timer 실측

---

## Why This Is Next
- 직전 P0 종결 후 가장 큰 구조적 위험은 **GitHub vs 서버 drift 자체**.
- drift 가 잡혀야 후속 mock_providers / base.py 패치도 안전하다.
- RUNNER_RULES 3장의 직접 침해 → 다른 모든 P0 의 검증 전제를 무력화.

---

## Minimal Scope
- 코드 수정 0
- 서버 read-only 실측 명령 7개 (모두 비-destructive)
- 결과 박제 후 drift 채널 후보 2개 이하로 좁힘
- 그 이후 단계 (실제 차단 / 가드레일 도입) 는 별 P0 분기

---

## Exact Files To Change
이번 단계 : **없음** (실측만)

다음 단계 (운영자 출력 수신 후) :
- 결과 박제용 `HANDOFF_LOG.md` / `TASK_BOARD.md` 만 갱신 가능
- 앱 코드 수정은 본 P0 종결 후 별 P0 로 재진입

---

## Files Forbidden To Change
- `app/providers/anthropic_provider.py` (본 P0 대상이지만 수정 절대 금지 — 실측만)
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
- prompt / model / max_tokens / config
- **서버 wide pull / destructive 명령 일체 금지**

---

## Validation Steps
이번 단계 (운영자 서버에서 복붙 실행, 모두 read-only) :

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

판정 매트릭스 (다음 세션에서 운영자 출력으로 채움) :

| 신호 | D1 | D2 | D3 | D4 | D5 |
|---|---|---|---|---|---|
| `git log` 결과가 작업 브랜치 sha | ✓ | ? | ✗ | ✗ | ✓ |
| `git log` 결과가 다른 브랜치 sha | ✓ | ✓ | ✗ | ✗ | ? |
| `*.bak*` 파일 존재 | ✗ | ✗ | ✓ | ✗ | ✗ |
| `git status` 가 modified 표시 | ✗ | ✗ | ? | ✓ | ✗ |
| `git diff origin/...` 결과 비어있음 | ✓ | ✓ | ? | ✗ | ✓ |
| `git diff origin/...` 결과 차이 있음 | ✗ | ✗ | ? | ✓ | ✗ |
| sha256sum 이 GitHub 본과 동일 | ✓ | ✓ | ? | ✗ | ✓ |
| mtime 이 본 세션 적용 이전 | ✓ | ✓ | ✓ | ✓ | ✓ |

---

## Recommendation
**APPROVE (진입 박제 단계)** — 실측 명령 발신 완료, 운영자 출력 수신 대기.

운영자 결정 기록 (누적):
- 직전 세션 (08:37 KST) : P0 종결, 후보 A/B/C 중 1개 선택 요청
- 본 세션 (08:41 KST) : 후보 A 채택 → 실측 단계 진입

다음 세션 트리거:
- 운영자가 위 7개 명령 출력을 그대로 본 채팅에 회신
- 추가로 "최근 24시간 내 anthropic_provider.py 직접 수정 여부" 1줄 기억 회신
- 본 세션 다음 세션에서 분석 + 확정 + HANDOFF_LOG 박제

---

## Next Handoff Rule
- 운영자 출력 수신 후 다음 세션에서 분석 + 결론 박제
- 결론에 따라 본 P0 종결 (drift 채널 식별 완료) 또는 새 가설 분기
- 본 P0 종결 시 후보 B (mock_providers kwarg) 또는 후보 C (base.py drift) 로 교체
