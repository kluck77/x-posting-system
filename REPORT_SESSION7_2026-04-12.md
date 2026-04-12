# 세션 7 작업 보고서 (최종)
**날짜:** 2026-04-12 (UTC 00:00 ~ 04:30)
**브랜치:** `claude/fix-providers-404-401`
**커밋:** `a560876` → `f982794` → `541090a` → `30f4572` → `d179145` → `165d306`

---

## 1. 작업 목표

세션 6 이후 서버에서 발생하던 AI 프로바이더 장애 3건(Gemini 404, Perplexity 401, Anthropic 구모델)을 복구하고, 전체 파이프라인 정상 작동을 검증하며, 발견된 보안/효율 이슈를 즉시 수정한다.

---

## 2. 수행 작업

### Phase 1: 프로바이더 장애 진단 & 복구

**Gemini 404 (Researcher)**
- 원인: `gemini-2.0-flash` 모델 2026.03.06 deprecated
- 수정: `gemini-2.0-flash` → `gemini-2.5-flash`
- 파일: gemini_provider.py:17, telegram_service.py:360
- 서버 curl 검증: HTTP 200 OK

**Anthropic 구모델 (Reviewer)**
- 원인: `claude-sonnet-4-20250514` — 10개월 전 스냅샷
- 수정: → `claude-sonnet-4-6` 최신
- 파일: anthropic_provider.py:24
- 서버 curl 검증: HTTP 200 OK

**Perplexity 401 (FactChecker)**
- 원인: API 키 만료 (모델/엔드포인트 정상)
- 수정: 운영자가 키 재발급, .env 갱신
- 서버 curl 검증: HTTP 200 OK

### Phase 2: API 비용 분석

server.log 기반으로 7일간 프로바이더 호출 패턴 분석.

**핵심 발견:**
- AI API가 과소비한 게 아니라, 아예 호출조차 거의 안 되고 있었음
- 대부분의 파이프라인이 [1/6] "이미 등록된 URL"에서 종료
- 4/10에 1,296건 파이프라인 진입 / 실제 신규 통과 5건 (통과율 0%)
- Anthropic이 전체 AI 비용의 87% 차지 (정상 운영 시)
- 월간 추정: $17~41 (위험 수준 아님)

### Phase 3: RSS 죽은 피드 복구

DNS 에러 원인 분석 결과 NXDOMAIN (도메인 자체 폐쇄) 확인:
- 매일경제: `rss.mk.co.kr` → `www.mk.co.kr/rss/30000001/` (도메인 이전)
- Reuters: 공개 RSS 완전 폐쇄 → 제거
- AP News: 공개 RSS 폐쇄 → 제거

RSS 피드 11개 → 9개. 매 60초 불필요 DNS 에러 3건 제거 (일 4,320건).

### Phase 4: 보안 — Gemini API 키 로그 마스킹

httpx가 에러 메시지에 전체 URL(?key=AIzaSy... 포함)을 노출하는 문제 발견.
- gemini_provider.py: 에러 핸들러에서 API 키 → `***` 치환
- telegram_service.py: 동일 처리
- server.log에 API 키 평문 노출 차단

### Phase 5: 성능 — news_monitor 중복 URL 사전 필터

서버 재시작 시 _seen_urls(메모리) 초기화 → 모든 기사(~195건)가 "신규"로 판정 → Orchestrator+AITeam 불필요 생성 반복 문제.
- full_pipeline() 호출 전에 DB URL 존재 체크 추가
- Orchestrator 생성 자체를 차단 (이전: [1/6]에서 차단)
- 사이클 요약 로그 추가: 수집/신규/DB중복/파이프라인 카운트

**적용 후 효과:**
- 첫 사이클(재시작 직후): 수집=195, DB중복=23건 사전 차단
- 이후 사이클: 수집=195, 신규=4, DB중복=1, 파이프라인=1
- "이미 등록된 URL" 에러: 90%+ 감소

---

## 3. End-to-End 검증 결과

기사 "미·이란 첫 종전협상 결렬" (source_id=982, draft_id=967)로 전체 파이프라인 테스트:

| 단계 | 프로바이더 | 결과 | 소요 |
|---|---|---|---|
| [1/6] 소스 저장 | — | ✅ | 0초 |
| [2/6] Researcher | Gemini | ⚠️ 429 (rate limit, fail-open) | 0초 |
| [3/6] DraftWriter | OpenAI | ✅ 성공 | 5초 |
| [4/6] FactChecker | Perplexity | ✅ verified=True, high | 3초 |
| [5/6] Reviewer | Claude | ✅ risk=medium | 15초 |
| [6/6] 분류 확정 | — | ✅ policy/medium | 0초 |
| 텔레그램 카드 | — | ✅ msg_id=741 | 1초 |
| 승인 → 게시 | X Mock | ✅ mock_3512846241 | — |

**총 소요: 26초.** OpenAI + Perplexity + Claude 3개 프로바이더 정상 작동 확인.
Gemini만 429 (무료 티어 rate limit) → 이후 자동 해소 확인.

---

## 4. 변경 파일 목록

| 파일 | 변경 내용 |
|---|---|
| `gemini_provider.py` | 모델 2.0→2.5, API 키 로그 마스킹 |
| `anthropic_provider.py` | 모델 업그레이드 |
| `rss_fetcher.py` | 죽은 피드 3곳 제거/교체 |
| `telegram_service.py` | 번역 모델 2.0→2.5, API 키 로그 마스킹 |
| `news_monitor.py` | DB URL 사전 중복 체크, 사이클 요약 로그 |

**금지 파일 무접촉 확인:**
- top5_briefing_service.py ✅
- orchestrator.py ✅
- rate_limiter.py ✅

---

## 5. 커밋 체인 (7개)

```
a560876  fix: update Gemini (2.5-flash) + Anthropic (sonnet-4-6) model names
f982794  fix: remove dead RSS feeds (NXDOMAIN) and update URLs
541090a  fix: remove AP News RSS feed (also discontinued, returns 404)
30f4572  fix: update remaining gemini-2.0-flash to 2.5-flash in telegram_service
01f9b77  docs: add session 7 handoff and report
d179145  security: mask Gemini API key in error log messages
165d306  perf: add DB URL pre-check in news_monitor before full_pipeline
```

---

## 6. 발견된 추가 이슈

| 이슈 | 심각도 | 설명 |
|---|---|---|
| Gemini 429 rate limit | 🟡 | 무료 티어 한계, 자동 해소 확인됨 |
| OperatorHints AttributeError | 🟡 | fail-open, 별도 수정 필요 |
| 서버 dirty worktree | 🟡 | git checkout 불가, 파일별 덮어쓰기 유지 |
| gpt-4o-mini API 퇴역 예정 | 🟢 | 아직 유효, 장기 전환 필요 |

---

## 7. 다음 우선순위

1. Gemini 포함 6단계 완주 재검증 (다음 신규 기사 시 자연 확인)
2. Top5 05:00 KST 자연 발동 실관측
3. OperatorHints 수정
4. dirty worktree 정리

---

## 서버 최종 상태

```
서비스:     PID 247452, 정상 가동
텔레그램:   봇 정상
RSS:       9피드 수집 (170개+)
DNS:       전체 정상
프로바이더: OpenAI ✅ / Claude ✅ / Perplexity ✅ / Gemini ✅(429해소) / Grok 🔘미테스트
중복필터:  DB 사전체크 활성 (90%+ 불필요 파이프라인 제거)
```
