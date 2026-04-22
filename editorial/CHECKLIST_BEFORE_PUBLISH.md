# Before Publish Checklist
# 발행 전 최종 체크리스트

**사용 시점**: Telegram 승인 버튼 누르기 직전, 이 7개를 순서대로 확인한다.
**소요 시간**: 1분 이내
**기준 문서**: editorial/CONSTITUTION.md

---

## 필수 (모두 통과해야 발행)

- [ ] **Frame test** — 이 글은 "사건 나열"이 아니라 하나의 명확한 프레임(Power Fight / Timeline Collapse / Signal vs Noise / Compounding Bet 등)으로 자르고 있는가?
  - *Does the post cut through one clear frame, not a list of events?*

- [ ] **Stake test** — "누가 이기고, 누가 지고, 얼마짜리인가"가 글 안에 명시되어 있는가?
  - *Does the reader know who wins, who loses, and how much?*

- [ ] **Ending test** — 마지막 줄이 RT·저장·팔로우를 유발하는가? (숫자·날짜·선언·forcing function 중 하나)
  - *Does the last line make the reader screenshot, bookmark, or quote?*

- [ ] **1차 소스 URL** — DART 공시번호 / 국회의안 링크 / 한은 보도자료 URL / 금감원 원문 중 최소 1개가 포스트 안에 있는가?
  - *At least one primary source URL or filing number included?*

- [ ] **금지어 클린** — banned_terms.yaml의 ai_tells / hedge / formula_closers 항목이 없는가?
  - *No banned terms from editorial/banned_terms.yaml?*

---

## 시리즈 포스트일 때만 추가 확인

- [ ] **시리즈 컨벤션** — Hook 고정 템플릿과 Ending 고정 템플릿이 SERIES_SPEC.md 형식과 일치하는가?
  - *Hook and ending match the series template in SERIES_SPEC.md?*

---

## Market-moving claim이 있을 때만

- [ ] **2-source rule** — 시장에 영향을 줄 수 있는 주장이 있다면 2개 이상의 독립 소스로 확인됐는가?
  - *Any market-moving claim verified by 2+ independent sources? (Reuters rule)*

---

## Fail 처리

- 하나라도 [ ]로 남아있으면 → **Telegram에서 "거절"** → 편집장 큐로 반환
- Stake / Frame test 실패 → editorial/system_prompts/editor_in_chief.md 재실행
- Ending test 실패 → editorial/system_prompts/ending_checker.md 재실행
- 금지어 실패 → editorial/system_prompts/voice_checker.md 재실행

---

*v1 — 2026-04-22 | 기준 문서: editorial/CONSTITUTION.md*
