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
- [ ] 운영 서버에 파일 선택 적용 (Appendix A)
- [ ] 실제 드래프트 1건 통과시켜 로그 수집 (Appendix B)
- [ ] 다음 실패 발생 시 Appendix B.2로 분류
- [ ] Appendix B.3 트리거 충족 시에만 Phase 8-β 요청
- [ ] Problem 6 상태 소재 확인 (별도 트랙으로 분리됨)

---

## 결정 확정 (APPROVED 2026-04-08)

- **Problem 6와 Phase 8-α는 별도 트랙으로 분리한다.**
- Problem 6는 지금 재구축/배포하지 **않는다**.
- Phase 8-α 로깅만 단독 배포한다.
- "Observe first, decide later" 원칙에 따라 수집된 로그 기반으로 8-β 여부를 판단한다.

이유:
- Problem 6는 어디에도 실체가 없음 → 재구축은 추측 기반이 됨
- Phase 8-α는 순수 진단 목적 → 다른 변경과 묶으면 관측 노이즈가 증가
- 번들링 시 진단 가치 감소

---

## Appendix A. 서버 적용 런북 (단일 파일, file-select only)

**적용 대상**: `app/providers/anthropic_provider.py` (이 파일 **하나만**)

### A.1 사전 확인
```bash
cd /path/to/x-posting-system
git status                    # working tree clean 이어야 함
git rev-parse HEAD             # 현재 서버 커밋 기록해 둘 것 (롤백용)
git log -1 -- app/providers/anthropic_provider.py
```

### A.2 원격 가져오기
```bash
git fetch origin claude/phase-8-alpha-logging-Ju1nF
git rev-parse origin/claude/phase-8-alpha-logging-Ju1nF
# 기대값: 6433ea8 이상 (PHASE_8_ALPHA_REPORT.md 포함된 상태)
# anthropic_provider.py 변경 자체는 cecd4ab에 있음
```

### A.3 파일 하나만 체크아웃
```bash
git checkout origin/claude/phase-8-alpha-logging-Ju1nF -- \
    app/providers/anthropic_provider.py
```
**⚠️ 다른 파일은 절대 체크아웃하지 말 것.**
`telegram_service.py`, `orchestrator.py`, `.env`, 대시보드, 프롬프트 상수 건드리면 이번 배포 원칙 위반.

### A.4 검증
```bash
python3 -m py_compile app/providers/anthropic_provider.py
python3 -c "from app.providers.anthropic_provider import AnthropicReviewer, AnthropicDraftWriter; print('import OK')"
git diff HEAD -- app/providers/anthropic_provider.py  # 변경 없어야 정상 (체크아웃 후)
git status                    # anthropic_provider.py만 수정된 상태
```

### A.5 서비스 재시작
운영자 표준 절차 사용 (systemctl / pm2 / docker 등). 재시작 후:
```bash
# 재시작 직후 로그에 [Phase8α] 라인이 나오는지 확인 (최초 드래프트 호출 시)
tail -f <로그파일> | grep Phase8α
```

### A.6 롤백 경로
문제 발생 시 A.1에서 기록한 이전 커밋으로 복구:
```bash
git checkout <이전_커밋_SHA> -- app/providers/anthropic_provider.py
python3 -m py_compile app/providers/anthropic_provider.py
# 서비스 재시작
```

### A.7 로그 레벨 주의
- `raw_content_preview` 라인은 `DEBUG` 레벨.
- 운영 로그가 `INFO` 필터인 경우 해당 라인은 **보이지 않음**.
- 진단 기간 동안에만 `app.providers.anthropic_provider` 로거를 `DEBUG`로 승격 권장.
- 로그 설정 변경이 부담스러우면, `raw_content_preview` 없이도 Appendix B.1의 다른 라인들로 분류 가능.

---

## Appendix B. 관측 체크리스트 (Observation Checklist)

### B.1 무엇을 볼 것인가 (grep 패턴 + 기대 라인)

**필수 1차 관측 (INFO)**
```bash
grep "\[Phase8α\]\[Claude Reviewer\] request"  <로그>
grep "\[Phase8α\]\[Claude Reviewer\] response" <로그>
grep "\[Phase8α\]\[Claude Reviewer\] parsed"   <로그>
```

기대 라인 (정상 흐름 3종 1세트):
```
[Phase8α][Claude Reviewer] request  model=... max_tokens=1024 title='...' user_msg_len=<N> has_research=<bool> has_factcheck=<bool>
[Phase8α][Claude Reviewer] response http=200 content_len=<N>
[Phase8α][Claude Reviewer] parsed   risk=<...> category=<...> action=<...> body_len=<N>
```

**2차 관측 (DEBUG, 선택)**
```bash
grep "\[Phase8α\]\[Claude Reviewer\] raw_content_preview" <로그>
```

**DraftWriter 경로 (참고)**
```bash
grep "\[Phase8α\]\[Claude DraftWriter\]" <로그>
```

**수집해야 할 최소 샘플**
- 정상 승인 케이스 × 1건 이상
- 실패/에러 케이스 × 1건 이상 (발생 시)
- `risk_level`이 high 또는 reject로 분류된 케이스 × 1건 이상 (발생 시)

### B.2 다음 실패를 어떻게 분류할 것인가

실패 발생 시 로그를 아래 표로 분류하여 GPT에 보고한다.

| 카테고리 | 진단 로그 증상 | 가능한 원인 | 8-β 필요도 |
|---|---|---|---|
| **F1. HTTP 실패** | `request` 라인 있음, `response` 라인 **없음**, `Claude Reviewer 오류` 로그 존재 | 네트워크 / 인증 / 레이트리밋 | **낮음** — 8-β 무관, 운영 이슈 |
| **F2. 빈 응답** | `response http=200 content_len=0` 또는 매우 작음(<50) | Claude가 max_tokens 절단 또는 빈 본문 반환 | **중간** — max_tokens 조정 별도 판단 |
| **F3. JSON 파싱 실패** | `response` 라인 있음, `parsed` 라인 **없음**, `Claude Reviewer 오류: ... JSONDecodeError` | Claude가 ```json ...``` 펜스로 감싸거나 프리앰블 텍스트 포함 | **높음** — **8-β 정당화 사유 #1** |
| **F4. 필드 누락** | `parsed risk=None` 또는 `category=None` 또는 `action=None` | Claude가 JSON은 리턴했지만 스키마 위반 | **높음** — **8-β 정당화 사유 #2** (스키마 강제 또는 fallback 필요) |
| **F5. 본문 길이 초과** | `parsed body_len > 270` | 프롬프트 준수 실패 | **중간** — 프롬프트 조정 별도 판단 (8-β와 분리) |
| **F6. 리스크 오판** | `parsed risk=low action=approve` 인데 정치/정책/사회 카테고리 | 안전 규칙 무시 | **낮음 (8-β 무관)** — 프롬프트 강화 트랙 |
| **F7. 관측 자체 실패** | `[Phase8α]` 라인이 하나도 안 보임 | 로깅 패치 미적용 또는 로그 레벨 필터 | **즉시** — Appendix A.7 확인 |

**보고 템플릿** (GPT에 전달 시)
```
카테고리: F?
발생 빈도: N/M (N=실패, M=전체 샘플)
샘플 로그 (3줄 1세트):
  [Phase8α][Claude Reviewer] request ...
  [Phase8α][Claude Reviewer] response ...
  [Phase8α][Claude Reviewer] parsed ... (있으면)
raw_content_preview (있으면):
  ...
```

### B.3 Phase 8-β가 정당화되는 조건 (트리거)

**하나라도 충족되면** 8-β 설계 요청 가능:

- [ ] **T1**. F3 (JSON 파싱 실패)가 연속 2건 이상, 또는 전체 샘플의 10% 이상
- [ ] **T2**. F4 (필드 누락)가 연속 2건 이상, 또는 전체 샘플의 10% 이상
- [ ] **T3**. `raw_content_preview`에서 ```` ```json ```` / ```` ``` ```` 펜스 패턴이 1건이라도 확인됨
- [ ] **T4**. `raw_content_preview`에서 JSON 앞뒤로 설명 텍스트(프리앰블/포스트앰블)가 1건이라도 확인됨

**충족되지 않으면**:
- 8-β는 **아직 정당화되지 않음**
- 관측을 더 수집하거나, 다른 트랙(Problem 6, 프롬프트 튜닝 등)을 진행
- "관측 없이 sanitize 먼저 박자"는 금지 (= 원래 8-α의 존재 이유를 부정하는 행동)

**정당화된 경우 8-β 요청 템플릿**:
```
Phase 8-β 요청:
- 정당화 트리거: T? (근거 로그 첨부)
- 관측 샘플: N건 (정상 N1 / 실패 N2)
- 실패 카테고리 분포: F3=x건, F4=y건, ...
- raw_content_preview 대표 샘플 첨부
- 설계 요구: 로그 라인 제거 금지, max_tokens/프롬프트 변경 금지,
  sanitize 로직은 parsed 라인 직전 단계에만 삽입
```
