# PHASE_8_ALPHA_REPORT.md
# Phase 8-α 진단 로깅 작업 보고서 (GPT 전달용)
# 작성: Claude Code
# 브랜치: `claude/phase-8-alpha-logging-Ju1nF`
# 커밋: `cecd4ab`
# 기준일: 2026-04-08

---

## 0. 이 보고서의 목적

운영자가 이 파일을 그대로 GPT에 복붙하면, GPT가 다음 단계(Phase 8-β: sanitize / fence stripping 설계) 프롬프트를 정확히 짤 수 있도록 작성된 인수인계 문서다.

GPT가 보고 판단해야 할 3가지:
1. Phase 8-α가 **실제로 무엇을 로그하는지** (관측 계약)
2. **건드리지 않은 것**이 무엇인지 (다음 단계 제약)
3. **Problem 6가 이 브랜치에 없다**는 사실 (중요 불일치)

---

## 1. 적용된 결정 (Approved Decisions)

| 항목 | 결정 |
|------|------|
| 전략 | Option A — 기존 Problem 6 브랜치 상태 위에 번들 배포 |
| 실제 베이스라인 | **Problem 6 상태 부재** → MVP 베이스라인 위에 로깅 전용 적용 (운영자 확인) |
| 대상 브랜치 | `claude/phase-8-alpha-logging-Ju1nF` (세션 지정) |
| 배포 단위 | 번들 (분리 금지) |
| 범위 | **로깅 전용 / 동작 변경 없음** |

---

## 2. 실제 변경 내역 (Actual Changes)

### 수정된 파일 (단 1개)
- `app/providers/anthropic_provider.py` — `+36 / -1`

### 수정되지 않은 파일 (의도적)
- `app/services/telegram_service.py` — **Problem 6 상태가 없어서 보존할 것이 없음**
- `app/orchestrator.py`
- 대시보드 파일 일체
- `.env` / `app/config.py`
- 프롬프트 상수 (`DRAFT_SYSTEM_PROMPT`, `REVIEW_SYSTEM_PROMPT`)
- `max_tokens` (1024 유지)
- Problem 7 / 9 관련 파일 일체

---

## 3. 추가된 진단 로그 (관측 계약)

모든 로그는 `[Phase8α]` 프리픽스를 가진다. grep/필터 기준으로 사용 가능.

### 3.1 AnthropicDraftWriter._call_claude

**요청 직전 (INFO)**
```
[Phase8α][Claude DraftWriter] request model=claude-sonnet-4-20250514 max_tokens=1024 user_msg_len=<N>
```

**응답 직후 (INFO)**
```
[Phase8α][Claude DraftWriter] response http=<200> content_len=<N>
```

**응답 직후 (DEBUG)**
```
[Phase8α][Claude DraftWriter] raw_content_preview=<repr(content[:200])>
```

### 3.2 AnthropicReviewer.review_and_refine

**요청 직전 (INFO)**
```
[Phase8α][Claude Reviewer] request model=claude-sonnet-4-20250514 max_tokens=1024 title='<50자>' user_msg_len=<N> has_research=<bool> has_factcheck=<bool>
```

**응답 직후 (INFO)**
```
[Phase8α][Claude Reviewer] response http=<200> content_len=<N>
```

**응답 직후 (DEBUG)**
```
[Phase8α][Claude Reviewer] raw_content_preview=<repr(content[:200])>
```

**JSON 파싱 직후 (INFO)**
```
[Phase8α][Claude Reviewer] parsed risk=<low|medium|high> category=<...> action=<approve|review|reject> body_len=<N>
```

**기존 로그 (그대로 유지)**
```
[Claude Reviewer] 완료: risk=<...>
```

### 3.3 명시적으로 하지 않은 것
- raw content sanitize 없음
- ```json ... ``` 펜스 제거 없음
- try/except 흐름 변경 없음
- 반환값 shape 변경 없음
- 프롬프트 문자열 수정 없음

---

## 4. 검증 결과

| 항목 | 결과 |
|------|------|
| `py_compile app/providers/anthropic_provider.py` | ✅ SYNTAX OK |
| `pytest tests/test_providers.py` | ✅ 7/7 passed |
| `pytest tests/test_telegram_service.py` | ✅ 10/10 passed |
| 전체 실행 가능 테스트 | ✅ 69/69 passed |
| 제외된 테스트 | `test_e2e.py`, `test_x_publisher.py` (기존 `requests_oauthlib` 미설치 이슈 — 이번 패치와 무관) |

---

## 5. Git 상태 (GitHub 최신화 확인)

```
브랜치     : claude/phase-8-alpha-logging-Ju1nF
로컬 HEAD  : cecd4ab
원격 HEAD  : cecd4ab  ← 동일
상태       : working tree clean, up to date with origin
```

커밋 메시지:
```
feat(phase-8α): add diagnostic logging to Anthropic provider

Add structured [Phase8α] log lines in AnthropicDraftWriter._call_claude
and AnthropicReviewer.review_and_refine to observe request parameters,
HTTP status, raw response length, debug-level content preview, and
parsed risk/category/action fields. Logging-only change — no behavior
modification, no prompt/max_tokens/sanitization changes.
```

---

## 6. 서버 적용 명령 (file-select only)

```bash
cd /path/to/x-posting-system
git fetch origin claude/phase-8-alpha-logging-Ju1nF
git checkout origin/claude/phase-8-alpha-logging-Ju1nF -- app/providers/anthropic_provider.py
python3 -m py_compile app/providers/anthropic_provider.py
# 서비스 재시작 (운영자 표준 절차)
```

---

## 7. 🚨 중요 불일치: Problem 6 상태 부재

**GPT는 이 섹션을 반드시 읽고 다음 프롬프트를 설계해야 한다.**

원래 지시서에는 다음이 전제되어 있었다:
- `anthropic_provider.py`에 Problem 6 상태가 이미 있어야 함
- `telegram_service.py`에 Problem 6 한국어 요약 렌더링이 이미 있어야 함

실제 이 브랜치(`claude/phase-8-alpha-logging-Ju1nF`), `origin/main`, 어느 원격 브랜치에도 Problem 6 변경은 **존재하지 않는다**. 두 파일 모두 초기 MVP 커밋(`ee83480`) 상태 그대로다.

운영자가 "MVP 베이스라인 위에 로깅 전용 적용"을 승인했기 때문에 이 작업은 의도대로 완료되었지만, **Problem 6 작업은 여전히 별도 과제로 남아 있다**.

### GPT가 판단해야 할 것
- Problem 6가 다른 브랜치/세션에 있는가? → 있다면 해당 브랜치명을 운영자가 확인해 주어야 함
- Problem 6와 Phase 8-α를 스택 작업으로 처리할 것인가, 독립 작업 아이템으로 분리할 것인가?
- Problem 6를 이 브랜치에 합류시킬 경우, Phase 8-α 로그의 관측 계약이 바뀌는가?

---

## 8. 다음 단계 권장 (Phase 8-β 설계 힌트)

Phase 8-α는 **진단 수집 단계**다. 운영자는 아래 순서대로 진행해야 한다:

1. 이 로깅 패치를 운영 서버에 적용
2. 실제 드래프트 1건 이상을 리뷰어까지 통과시킴
3. 다음 3가지 로그 라인을 수집:
   - `[Phase8α][Claude Reviewer] response http=<...> content_len=<...>`
   - `[Phase8α][Claude Reviewer] raw_content_preview=<...>` (DEBUG 레벨)
   - `[Phase8α][Claude Reviewer] parsed risk=<...> category=<...> action=<...> body_len=<...>`
4. 로그를 GPT에 전달 → GPT가 실제 관측된 문제(예: Claude가 ```json 펜스로 감싸는지, content_len이 max_tokens 한계에 붙었는지, JSON 파싱 실패 빈도 등)에 맞춰 Phase 8-β sanitize 로직을 설계

### 주의사항
- 운영 환경 로그 레벨이 `DEBUG`를 필터링하는 경우 `raw_content_preview` 라인이 보이지 않을 수 있다. 진단 기간 동안만 해당 로거를 `DEBUG`로 승격하거나, 임시로 프리뷰 라인을 `INFO`로 올릴 수 있다.
- Phase 8-β에서 sanitize/fence stripping을 추가할 때는 **기존 로그 라인을 제거하지 말 것**. 사후 비교를 위해 유지 필요.

---

## 9. GPT에게 전달할 질문 템플릿

운영자가 GPT에 다음 단계 프롬프트를 요청할 때 사용할 수 있는 템플릿:

```
Phase 8-α(진단 로깅)가 커밋 cecd4ab로 `claude/phase-8-alpha-logging-Ju1nF`
브랜치에 배포되었다. PHASE_8_ALPHA_REPORT.md를 기준으로 다음 2가지를 설계해 줘:

1. Problem 6 상태가 어디에도 없다는 것이 확인되었음.
   Problem 6를 재구축해야 하는가, 아니면 별도 작업으로 분리할 것인가?
   결정 근거와 함께 답해 줘.

2. Phase 8-α 로그 관측 후 Phase 8-β(sanitize) 설계 기준을 정리해 줘.
   단, 관측 전 단계이므로 "로그가 이렇게 나오면 → 이렇게 처리"
   형식의 분기 설계로 작성할 것.

제약 조건:
- anthropic_provider.py 로그 라인 제거 금지
- max_tokens, 프롬프트 수정 금지
- orchestrator / dashboard / .env 변경 금지
```

---

## 10. 참조 파일 (GPT가 함께 읽어야 할 문서)

- `CLAUDE_CODE_HANDOFF.md` — 전체 인수인계 구조
- `COMMANDER_BRIEF.md` — 운영 원칙
- `README.md` — 시스템 개요
- `app/providers/anthropic_provider.py` — 이번 변경 대상 파일 (HEAD)

---

## 11. 체크리스트 (운영자용)

- [x] 로컬 브랜치에 커밋 완료 (`cecd4ab`)
- [x] 원격 브랜치 푸시 완료 (`origin/claude/phase-8-alpha-logging-Ju1nF`)
- [x] 문법 검사 통과
- [x] 단위 테스트 통과 (69/69)
- [x] 이 보고서 작성 완료
- [ ] 운영 서버에 파일 선택 적용
- [ ] 실제 드래프트 1건 통과시켜 로그 수집
- [ ] GPT에 본 보고서 + 수집된 로그 전달
- [ ] Problem 6 상태 소재 확인 (별도 과제)
