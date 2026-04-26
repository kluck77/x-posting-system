# Editorial 자산 인덱스 v2
# 계정: @sskorea02
# 버전: v2.0 | 2026-04-22
# 용도: editorial/ 디렉토리 전체 자산의 단일 진입점.
#       새 작업 시작 시 이 파일을 먼저 읽는다.

---

## 자산 맵

| # | 파일 | 언어 | 사용 시점 | 파이프라인 단계 | 비고 |
|---|---|---|---|---|---|
| 1 | CONSTITUTION.md | 한국어 | 모든 작업 전 참조 | — | 전체 자산의 source of truth |
| 2 | CHECKLIST_BEFORE_PUBLISH.md | 한국어 | 텔레그램 승인 직전 | 승인 단계 | 7개 체크박스, 1분 이내 |
| 3 | banned_terms.yaml | YAML | 모든 critic prompt 참조 | Review·Voice 단계 | 단일 금지어 원본 |
| 4 | system_prompts/editor_in_chief.md | 한국어 | Grok Custom Agent 설정 시 1회 | 편집장 단계 | system prompt 전문 |
| 5 | system_prompts/voice_checker.md | 한국어 | Draft 완료 후 | Review 단계 (Claude) | JSON output 반환 |
| 6 | system_prompts/hook_checker.md | 한국어 | Draft 완료 후 | Draft→Review 사이 | JSON output 반환 |
| 7 | system_prompts/ending_checker.md | 한국어 | Draft 완료 후 | Draft→Review 사이 | JSON output 반환 |
| 8 | system_prompts/fact_checker.md | 한국어 | Factcheck 단계 | Factcheck (Perplexity) | publish_block 플래그 |
| 9 | series/SERIES_SPEC.md | 한국어 | 시리즈 포스트 작성 시 | Draft 단계 전 | 시리즈 5개 스펙 |
| 10 | INDEX.md | 한국어 | 신규 작업 시작 시 | — | 이 파일 |

---

## 실제 운영 흐름

소스 수집
    ↓
AI 초안 생성 (OpenAI)
    ↓
hook_checker — 훅 강도 평가 (JSON)
    ↓
voice_checker — 금지어·헷지·아첨 감지 (JSON)
    ↓
Review (Claude) — voice_checker 결과 반영
    ↓
Research (Gemini)
    ↓
fact_checker — 수치·소스·번역 정확도 (JSON + publish_block)
    ↓
Factcheck (Perplexity)
    ↓
텔레그램으로 초안 전송
    ↓
운영자가 초안 복사 → Grok (X Premium+) 에 붙여넣기
    ↓
Grok이 editor_in_chief.md 규칙으로 편집
    ↓
운영자가 CHECKLIST_BEFORE_PUBLISH.md 7개 확인
    ↓
X 수동 업로드

---

## publish_block 발생 시 처리 순서

1. fact_checker publish_block = true → 발행 중단. 소스 재확인.
2. hook_checker score 2 이하 → 훅 재작성 후 전체 재실행.
3. voice_checker flags 3개 이상 → voice 재작성 후 Grok 재실행.
4. ending_checker forbidden_match = true → 엔딩만 재작성.

---

## 버전 관리 원칙

- 모든 자산 변경은 CONSTITUTION.md 섹션 7 변경 이력에 기록.
- critic prompt 변경 시 banned_terms.yaml 동기화 필수.
- 시리즈 추가·변경은 SERIES_SPEC.md + CONSTITUTION.md 섹션 6 동시 업데이트.
- editor_in_chief.md 변경 시 반드시 v3으로 버전 올림.

---

*Index v2.0 완료 | 2026-04-22*
