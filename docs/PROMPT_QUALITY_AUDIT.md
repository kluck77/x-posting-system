# Prompt Quality Audit — @cheesesvav

실제 AI 출력물 20~30개를 모아 점검할 때 사용하는 체크리스트.
코드 연결 없음 — 운영자가 수동으로 검토하는 문서.

---

## 사용법

1. 최근 승인/게시된 초안 20~30개를 `drafts` 테이블에서 추출
2. 각 항목에 대해 아래 체크리스트 적용
3. 문제 패턴이 3회 이상 반복되면 해당 프롬프트 지시문 수정 검토

```sql
SELECT id, hook, body, created_at
FROM drafts
WHERE approval_status IN ('APPROVED', 'PUBLISHED')
ORDER BY created_at DESC
LIMIT 30;
```

---

## 체크리스트

### A. AI 티 나는 표현

다음 표현이 hook 또는 body에 나타나면 즉시 수정 대상.

| 표현 | 왜 문제인가 | 대체 방향 |
|------|------------|----------|
| "In conclusion" | 에세이 말투, 소셜 미디어 부적합 | 삭제 또는 핵심만 남기기 |
| "Furthermore" / "Moreover" | 학술 보고서 어투 | "Also" → 아니면 문장 분리 |
| "Notably" / "It is worth noting" | AI 보고서 표지 어투 | 직접 서술로 대체 |
| "delve into" | GPT 특유 표현 | "look at", "break down" |
| "navigate" (비유적) | 과잉 어휘 | 직접 동사 사용 |
| "unprecedented" | 과장, 신뢰성 손상 | 구체적 수치로 대체 |
| "game-changer" | 클리셰 | 실제 영향 서술 |
| "This underscores" | 리포트 어투 | "This shows", 혹은 삭제 |
| "landscape" (비유적) | 과잉 어휘 | 구체적 명사로 대체 |
| "tapestry" | 과잉 어휘 | 삭제 |

**점검 방법:** VoiceGuard 로그(`style_warnings`)에서 자동 감지됨. 단일 초안 approval card에도 경고 표시됨 (최대 3개). 로그 없으면 수동 grep.

**현재 프롬프트 금지어 목록 (DraftWriter + Reviewer rewrite 공통, 2026-04 기준):**
furthermore / however / it is worth noting / it should be noted / notably /
delve into / game-changer / this underscores / unprecedented /
moreover / pivotal / moving forward / undeniably

**VoiceGuard 감지 중 아직 프롬프트 미반영 (향후 추가 검토):**
navigate / in the realm of / foster / as we look ahead / in today's X /
it's important to / it's imperative / undeniably / In conclusion

---

### B. 너무 딱딱한 표현

보도자료처럼 읽히는 초안 — 소셜 미디어 느낌이 없음.

징후:
- 문장이 30단어 이상 연속으로 이어짐
- 수동태 과다 사용 ("It was announced that...")
- 주어가 기관명으로 시작 ("The Bank of Korea today announced...")
- 인용부호 없이 정책 명칭 나열

**교정 방향:**
- 첫 문장을 질문이나 숫자로 시작
- 수동태 → 능동태
- 기관명 → 결과/영향 먼저 서술

---

### C. 설명 계정 톤과 안 맞는 표현

@cheesesvav는 "한국 내부 관점을 영어로 전달하는 해설가" 톤.
다음은 톤 불일치 징후:

| 불일치 유형 | 예시 | 수정 방향 |
|------------|------|----------|
| 중립 보도 톤 | "South Korea announced X" | "Here's what Koreans are actually saying about X" |
| 지나친 낙관 | "This is a huge opportunity for Korea" | 실제 커뮤니티 반응 포함 |
| 관광 홍보 어투 | "Korea's vibrant culture..." | 삭제 — 이 계정과 무관 |
| 지나치게 학술적 | "The macroeconomic implications of..." | "What this means for your portfolio" |
| 한국어 직역 느낌 | 어색한 어순, 조사 직역 | 영어 원어민 표현으로 재작성 요청 |

---

### D. 너무 과장된 훅

훅이 클릭베이트 수준이면 계정 신뢰성 손상.

경고 신호:
- "Everything is about to change"
- "You won't believe what Korea just did"
- 감탄부호 2개 이상 (`!!`)
- 근거 없는 "The biggest X ever"

**기준:** 훅의 주장을 body가 뒷받침하지 못하면 과장.
→ 훅을 낮추거나 body에 근거 추가.

---

### E. "왜 외국인에게 중요한지" 빠진 경우

한국 내부 이야기만 있고 글로벌 연결고리가 없는 초안.

점검 질문:
1. 이 포스트를 읽은 해외 투자자/연구자가 "나와 무슨 상관?" 이라고 할 것인가?
2. 달러/글로벌 시장/공급망/지정학 중 하나라도 언급되는가?
3. "Korea" 외 다른 나라/기관이 한 번이라도 언급되는가?

**3개 모두 해당하면:** Gemini researcher 프롬프트의 `context_for_foreigners` 지시문 강화 검토.

---

### F. 드리프트 패턴 점검

30개 샘플을 한꺼번에 보면서 전체 흐름 점검.

| 패턴 | 징후 | 대응 |
|------|------|------|
| 너무 랜덤 | 3개 연속으로 전혀 다른 카테고리 | TopicMemory 과다 사용 경고 확인 |
| 너무 소프트 | lifestyle / culture만 반복 | criteria Criteria 2(marketability) 점수 하락 추세 확인 |
| 라이프스타일 드리프트 | 음식/패션/여행 비율 ≥ 30% | 소스 필터링 강화 또는 거절 비율 점검 |
| 경제 과집중 | economy 태그 ≥ 60% | content-mix advisory 확인 (TopicMemory) |
| 반복 훅 형식 | 매번 같은 문장 구조 | DraftWriter 시스템 프롬프트 variety 지시 강화 |

---

## 점검 주기

- **매주 월요일:** 최근 7일 승인 초안 훑어보기 (5분 점검)
- **월 1회:** 30개 샘플 전수 점검 + 패턴 기록
- **분기 1회:** 위 결과를 바탕으로 DraftWriter/Reviewer 프롬프트 개선 여부 판단

---

## 기록 방법

문제 발견 시 `/note <draft_id> <문제 유형>` 으로 초안에 메모 남기기.

예:
```
/note 87 AI 어투: 'delve into' 사용됨
/note 91 훅 과장: body 근거 없음
/note 95 외국인 연결고리 없음
```

이 메모들이 쌓이면 다음 프롬프트 개선 시 근거 자료로 활용.

---

## 관련 파일

- `app/services/voice_guard.py` — AI 어투 자동 감지 (19 patterns)
- `app/services/quality_scorer.py` — score_draft, score_5criteria
- `app/services/topic_memory.py` — 카테고리 믹스 추적
- `app/providers/openai_provider.py` — DraftWriter 시스템 프롬프트
- `app/providers/anthropic_provider.py` — Reviewer 시스템 프롬프트
- `app/providers/gemini_provider.py` — Researcher 시스템 프롬프트
