# TASK_BOARD

이 문서는 **현재 단 1개의 문제** 만 전면에 둔다.
다른 모든 문제는 이 문제가 닫힐 때까지 대기한다.

---

## Updated At
2026-04-09 08:49 KST

## Updated By
Claude Code (claude/x-posting-ops-review-7hlxK)

## Current Stage
**1차 실측 완료. 후보 2개 그룹 (D3 강 / D1·D2 가능) 으로 좁힘.** 추가 1단계 확인 후 종결 가능.

## Current Priority
P0 — **서버 anthropic_provider.py 출처 미상 변경 채널 식별** (후보 A) — 진행률 ~70%

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

### 1차 실측 결과 (2026-04-09 08:49 KST)
- 서버 sha256 = 로컬 b62cc33 sha256 = `78498dd0...` (byte-identical)
- 서버 size = 로컬 size = 10178 bytes
- 서버 `git diff origin/claude/x-posting-ops-review-7hlxK` = 빈 출력
- → ★ 현재 시점 서버 == GitHub b62cc33 본 100% 일치 ★
- 서버 mtime = 2026-04-08 23:36:14 UTC = 본 세션 surgical checkout 시각
- 서버 git status -s = `M  app/providers/anthropic_provider.py` (surgical checkout 의 정상 부산물)
- 서버 git log -1 = `bde95b8 2026-04-05 v10` (그 이후 git tracked anthropic 변경 0)
- ★ `app/providers/anthropic_provider.py.bak` 실재 ★ (D3 의 강한 정황)
- 같은 디렉토리 `openai_provider.py.bak` 도 존재
- 다른 영역 `telegram_bot.py.bak`, `telegram_service.py.bak`, `.env.bak.*` 3종 산재

---

## Current Issue
**서버 anthropic_provider.py 출처 미상 변경 채널 식별 (후보 A)**

목표 : drift 채널을 후보 2개 이하로 좁힌다.
이번 단계 수정 : 0 (실측만)

### Drift 채널 가설 — 1차 실측 후 좁힘

| 가설 | 정의 | 1차 실측 결과 | 결론 |
|---|---|---|---|
| **D1** | 운영자가 다른 브랜치에서 직접 surgical checkout 후 commit 안 함 | `git log` 에 phase8 commit 0건 → surgical checkout (commit 안 만듦) 패턴과 정합 | **가능 (직접 증거 없음)** |
| **D2** | 다른 Claude Code 세션이 동일 서버에 surgical checkout | D1 과 구분 불가, 운영자 회신으로만 분리 가능 | **가능** |
| **D3** | `.bak` / stash 기반 수동 복원 | ★ `anthropic_provider.py.bak` 실재 ★ | **가장 강한 후보** |
| **D4** | 파일 매니저 / IDE / scp 업로드 | mtime / git status 모두 surgical checkout 패턴과 일치, 다른 채널 시그널 0 | **사실상 배제** |
| **D5** | 자동화 deploy hook | 시그널 0, .bak 산재 패턴은 사람 작업과 더 일치 | **사실상 배제** |

→ 본 세션에서 **D4 / D5 배제, 후보 D3 (강) + D1·D2 (가능) 두 그룹으로 좁힘**.

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

### 1차 실측 (완료, 2026-04-09 08:49 KST)
HANDOFF_LOG 의 본 항목 "운영자 서버 출력 (그대로 박제)" 참조.
결론: 서버 == GitHub b62cc33 본 byte-identical, .bak 실재.

### 2차 실측 (다음 단계, 운영자 복붙, 모두 read-only)
D3 vs D1·D2 단정을 위해 :

```
ls -la /root/x-posting-system/app/providers/anthropic_provider.py.bak
sha256sum /root/x-posting-system/app/providers/anthropic_provider.py.bak
diff /root/x-posting-system/app/providers/anthropic_provider.py.bak /root/x-posting-system/app/providers/anthropic_provider.py | head -30
git reflog --date=iso | head -20
git stash list
```

판정 시나리오 :
- `.bak` sha256 == 현재 파일 sha256 → 누군가 백업 직후 원본 무수정 → D3 약화 (왜 굳이 백업?)
- `.bak` 가 phase8 로깅 *없는* 옛 본 → D3 강화 ★ ".bak 만들고 그 위에 새 수정 얹음" 시나리오
- `.bak` 가 phase8 로깅 *포함* 옛 본 → D3 강화 (단, 어느 시점의 본이냐 확인)
- `git reflog` 에 surgical checkout 흔적 → D1/D2 약한 증거
- `git stash list` 에 안티 stash → 부수 정보

### 운영자 회신 1줄 (재요청)
"최근 24시간 내 anthropic_provider.py 를 운영자 본인이 직접 손댄 적이 있다 / 없다"
- 직전 세션에서 요청했으나 회신 미수신
- D1 vs D2 분리에 결정적

---

## Recommendation
**APPROVE (1차 좁힘 단계)** — D4/D5 배제, D3 (강) + D1·D2 (가능) 두 그룹 식별 완료.

운영자 결정 기록 (누적):
- 08:37 KST : 직전 P0 종결, 후보 A/B/C 중 1개 선택 요청
- 08:41 KST : 후보 A 채택 → 실측 명령 발신
- 08:49 KST : 1차 실측 결과 박제, 후보 2개 그룹으로 좁힘

다음 세션 트리거:
- 운영자가 2차 실측 5개 명령 출력 회신
- 추가로 "최근 24시간 내 직접 수정" 1줄 회신
- 다음 세션에서 D3 vs D1·D2 단정 또는 양쪽 인정 후 본 P0 종결

---

## Next Handoff Rule
- 운영자 출력 수신 후 다음 세션에서 분석 + 결론 박제
- 결론에 따라 본 P0 종결 (drift 채널 식별 완료) 또는 새 가설 분기
- 본 P0 종결 시 후보 B (mock_providers kwarg) 또는 후보 C (base.py drift) 로 교체
