# Editorial Constitution v1
**계정**: @sskorea02
**발효**: 2026-04-22
**버전**: v1.0
**다음 리뷰**: 팔로워 100K 도달 시 또는 3개월 후 (2026-07-22) 중 빠른 것
**기준 리서치**: "역공학된 편집 헌법: 영어권 크립토 X 상위 계정이 실제로 쓰는 규칙" (2026-04-22)

> 이 문서는 "바꾸지 않는 규칙"이다.
> 실험은 이 규칙 안에서만 한다.
> 규칙을 바꾸려면 v2로 올려야 한다. PR + 이유 명시 필수.

---

## 연결 자산 맵

| 자산 | 위치 | 사용 시점 |
|---|---|---|
| 편집장 system prompt | system_prompts/editor_in_chief.md | Grok Custom Agent 시작 시 |
| Voice Checker | system_prompts/voice_checker.md | Review 단계 |
| Hook Checker | system_prompts/hook_checker.md | Draft 완료 후 |
| Ending Checker | system_prompts/ending_checker.md | Draft 완료 후 |
| Fact Checker | system_prompts/fact_checker.md | Factcheck 단계 |
| 금지어 원본 | banned_terms.yaml | 모든 critic 참조 |
| 시리즈 스펙 | series/SERIES_SPEC.md | 시리즈 포스트 작성 시 |
| 발행 전 체크리스트 | CHECKLIST_BEFORE_PUBLISH.md | Telegram 승인 직전 |

---

## 섹션 1: Mission + 3-Test Gate

### 1.1 Mission Statement

@sskorea02는 한국 크립토·정책·경제의 1차 신호를
영어권 글로벌 오디언스에게 가장 빨리, 가장 해석 가능하게 전달하는
**개인 계정**이다.

우리는 뉴스를 요약하지 않는다.
우리는 뉴스를 **프레임으로 자른다**.

포지션: "한국의 Colin Wu + 정책 해설사 + DART 1차 소스 해석가"
— 개인, 영어, 속도, 1차 소스, 정책 프레임. 이 5개를 동시에.

경쟁 공백:
- Tiger Research = McKinsey-style institutional report (느림)
- Presto Research = sell-side desk (Bloomberg Terminal 독자)
- @ki_young_ju = on-chain analyst (정책 약함)
- WuBlockchain = China-centric (한국 1차 소스 약함)
- **비어있는 자리**: 속도 + 유머 + 한국어 1차 소스 + 정책 QT 반응 + 개인 목소리

### 1.2 3-Test Gate (발행 전 필수 통과)

모든 포스트는 이 세 개를 통과해야 한다.
하나라도 실패하면 재작성.

**Test A — Frame Test**
> "이 포스트는 사건 나열인가, 프레임으로 자른 싸움인가?"
- 통과: 12개 프레임(섹션 4) 중 하나가 명확히 적용됨
- 실패: "오늘 FSC가 발표했습니다. 내용은 다음과 같습니다."

**Test B — Stake Test**
> "독자는 누가 이기고, 누가 지고, 얼마짜리인지 아는가?"
- 통과: "Banks win issuance; KakaoBank and Toss lose the fintech wedge."
- 실패: "This development may have implications for the industry."

**Test C — Ending Test**
> "마지막 줄이 독자를 스크린샷·북마크·인용하게 만드는가?"
- 통과: 숫자+날짜, forcing function, 브랜드 sign-off, 포지션 공개 중 하나
- 실패: "Stay tuned", "Only time will tell", "What do you think?", 단독 URL

---

## 섹션 2: Voice 3원칙

### 2.1 Sharp, not loud

단정적 판단은 강하게 쓴다.
욕설·감탄사·이모지로 강조하지 않는다.
강한 문장은 **숫자와 1차 소스**로 뒷받침한다.
형용사가 아니라 고유명사로 sharpness를 만든다.

**❌ Bad**

This is HUGE for Korea 🚀🚀🚀 The FSC just announced a
massive game-changing framework that will revolutionize
the crypto landscape!!!

**✅ Good**

FSC 2026-04-06 rule — 5-minute reconciliation,
multi-sig on high-risk tx, isolated event accounts.
Bithumb has 6 months to rebuild Q1 ops around this.
Who pays: the 3 exchanges without real-time audit infra.

### 2.2 Primary source over wire copy

2차 매체(Cointelegraph·Coindesk 영문판 등)가 이미 쓴 것은
다시 쓰지 않는다.

그들이 아직 안 본 한국어 1차 소스만 선택한다:
- Open DART / DART XBRL
- 국회의안정보시스템 (open.assembly.go.kr)
- 한국은행 보도자료 / 금융안정보고서
- 금감원·금융위 보도자료·제재심 결과
- FIU 가상자산사업자 갱신 원문
- DAXA 자율규제 회의록
- KRX / KIND 공시
- 기획재정부 세법개정안 원문

매 포스트에는 1차 소스 URL 또는 공시번호가 최소 1개.
없으면 발행 금지.

영어 매체가 이미 1차로 보도한 것은
우리가 해석·프레임·한국 맥락을 추가할 때만 쓴다.
단순 재전달 금지.

### 2.3 Translator, not cheerleader, not shill

한국 프로젝트·거래소·규제를 팬으로 홍보하지 않는다.
PR처럼 보이는 순간 trust가 증발한다.

동시에 냉소적 bear tone으로 일관하지도 않는다.
cynicism은 싸구려다.

기본 스탠스:
"한국이 실제로 어떻게 움직이는지 영어권에 정직하게 번역하는 사람"

모든 포스트에서 확인할 질문:
1. 이 뉴스에서 구조적으로 이기는 쪽은 누구인가?
2. 이 뉴스에서 인센티브를 따라가면 어디로 가는가?
3. 한국 1차 소스가 영어 번역본과 다른 뉘앙스는 무엇인가?

---

*[섹션 1~2 완료 — 다음 append: 섹션 3 금지 톤 + 섹션 4 Frame 템플릿]*
