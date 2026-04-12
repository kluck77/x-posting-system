# 세션 7 작업 보고서
**날짜:** 2026-04-12 (UTC 00:00 ~ 03:40)
**브랜치:** `claude/fix-providers-404-401`
**커밋:** `a560876` → `f982794` → `541090a` → `30f4572`

---

## 1. 작업 목표

세션 6 이후 서버에서 발생하던 AI 프로바이더 장애 3건(Gemini 404, Perplexity 401, Anthropic 구모델)을 복구하고, 전체 파이프라인이 정상 작동하는지 검증한다.

---

## 2. 수행 작업

### Phase 1: 프로바이더 장애 진단 & 복구

**Gemini 404 (Researcher)**
- 원인: `gemini-2.0-flash` 모델이 2026.03.06 deprecated, 2026.06.01 shutdown 예정
- 수정: `gemini-2.0-flash` → `gemini-2.5-flash` (gemini_provider.py:17)
- 서버 curl 검증: HTTP 200 OK

**Anthropic 구모델 (Reviewer)**
- 원인: `claude-sonnet-4-20250514` — 10개월 이전 스냅샷
- 수정: → `claude-sonnet-4-6` 최신 (anthropic_provider.py:24)
- 서버 curl 검증: HTTP 200 OK

**Perplexity 401 (FactChecker)**
- 원인: API 키 만료 (모델명/엔드포인트는 정상)
- 수정: 운영자가 perplexity.ai/settings/api에서 키 재발급, .env 갱신
- 서버 curl 검증: HTTP 200 OK

### Phase 2: API 비용 분석

server.log 기반으로 7일간 프로바이더 호출 패턴 분석.

**핵심 발견:**
- AI API가 과소비한 게 아니라, 아예 호출조차 거의 안 되고 있었음
- 대부분의 파이프라인이 [1/6] "이미 등록된 URL" 에서 종료
- 4/10에 1,296건 파이프라인 진입 / 실제 신규 통과 5건 (통과율 0%)
- Anthropic이 전체 AI 비용의 87% 차지 (정상 운영 시)
- 월간 추정: $17~41 (위험 수준 아님)

### Phase 3: RSS 죽은 피드 복구

DNS 에러 원인 분석 결과 NXDOMAIN (도메인 자체 폐쇄) 확인:
- 매일경제: `rss.mk.co.kr` → `www.mk.co.kr/rss/30000001/` (도메인 이전)
- Reuters: 공개 RSS 완전 폐쇄 → 제거
- AP News: 공개 RSS 폐쇄 → 제거

RSS 피드 11개 → 9개. 매 60초 불필요 DNS 에러 3건 제거 (일 4,320건).

### Phase 4: 잔존 구모델 정리

`telegram_service.py:360` 번역 함수에 `gemini-2.0-flash` 잔존 발견.
→ `gemini-2.5-flash`로 교체. grep 전수 검사로 잔존 0건 확인.

### Phase 5: 서비스 안정화

- 봇 이중 프로세스 충돌 해결 (PID 2개 → pkill 후 단일 재시작)
- 텔레그램 Conflict 에러 자동 해소 확인
- 최종 서비스 정상 가동 확인

---

## 3. End-to-End 검증 결과

기사 "미·이란 첫 종전협상 결렬" (source_id=982)로 전체 파이프라인 테스트:

| 단계 | 프로바이더 | 결과 | 소요 |
|---|---|---|---|
| [1/6] 소스 저장 | — | ✅ | 0초 |
| [2/6] Researcher | Gemini | ⚠️ 429 (fail-open) | 0초 |
| [3/6] DraftWriter | OpenAI | ✅ 성공 | 5초 |
| [4/6] FactChecker | Perplexity | ✅ verified=True, high | 3초 |
| [5/6] Reviewer | Claude | ✅ risk=medium | 15초 |
| [6/6] 분류 확정 | — | ✅ policy/medium | 0초 |
| 텔레그램 카드 | — | ✅ msg_id=741 | 1초 |
| 승인 → 게시 | X Mock | ✅ mock_3512846241 | — |

**총 소요: 26초.** OpenAI + Perplexity + Claude 3개 프로바이더 정상 작동 확인.
Gemini만 429 (무료 티어 rate limit, 자동 풀림 대기).

---

## 4. 변경 파일 목록

| 파일 | 변경 내용 | 라인 |
|---|---|---|
| `app/providers/gemini_provider.py` | 모델명 2.0→2.5 | L17 |
| `app/providers/anthropic_provider.py` | 모델명 업그레이드 | L24 |
| `app/services/rss_fetcher.py` | 죽은 피드 3곳 제거/교체 | L29, L34-35 |
| `app/services/telegram_service.py` | 번역 경로 모델명 수정 | L360 |

**수정하지 않은 파일 (금지 목록 무접촉 확인):**
- `app/services/top5_briefing_service.py` ✅
- `app/orchestrator.py` ✅
- `app/services/rate_limiter.py` ✅
- `app/services/telegram_service.py` (번역 1줄 외 무접촉) ✅

---

## 5. 발견된 추가 이슈

| 이슈 | 심각도 | 설명 |
|---|---|---|
| Gemini API 키 로그 노출 | 🔴 | 에러 로그에 `?key=AIzaSy...` 평문 노출 |
| Gemini 429 rate limit | 🟡 | 무료 티어 한계, fail-open으로 운영 영향 없음 |
| news_monitor 중복 비효율 | 🟡 | 매 60초 대부분 중복 URL로 종료 |
| 서버 dirty worktree | 🟡 | git checkout 불가, 파일별 덮어쓰기 방식 유지 |

---

## 6. 다음 세션 권장 작업

1. Gemini 429 해소 후 Researcher 포함 전체 6단계 완주 재검증
2. Top5 05:00 KST 자연 발동 실관측
3. Gemini API 키 로그 마스킹 (보안)
4. news_monitor 중복 사전 필터 (효율)

---

## 7. 서버 상태 최종 확인

```
서비스:     PID 246954, 정상 가동
텔레그램:   봇 정상, Conflict 해소
RSS:       9피드 정상 수집 (170개)
DNS:       5개 API 호스트 모두 resolve OK
프로바이더: OpenAI ✅ / Claude ✅ / Perplexity ✅ / Gemini ⚠️429 / Grok 🔘미테스트
```
