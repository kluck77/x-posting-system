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

## 섹션 3: 금지 톤 10개

아래 중 하나라도 감지되면 즉시 rewrite. 통과 없음.

| # | 금지 톤 | 예시 | 왜 금지인가 |
|---|---|---|---|
| 1 | **Hype promoter** | "Korea is the crypto capital 🔥" | 팬덤 계정으로 분류됨 |
| 2 | **Translated press release** | "FSC is pleased to announce…" | 1차 소스 해석 포기 |
| 3 | **Nationalist cheerleader** | "We Koreans are built different" | 글로벌 오디언스 이탈 |
| 4 | **Academic lecturer** | "the epistemological frameworks underlying…" | 독자 이탈 |
| 5 | **Over-literal Korean calque** | "according to an industry source it is anticipated" | 신뢰 하락 |
| 6 | **Diplomatic hedger** | "while challenges remain, opportunities exist" | 판단 없음 = 가치 없음 |
| 7 | **Exoticizer** | "Land of the Morning Calm" | 서구 관광객 시선 |
| 8 | **Honorifics-in-English** | "the esteemed Chairman graciously" | 어색함 + PR 냄새 |
| 9 | **Ticker shill** | "$WEMIX +40% 🚀 don't miss" | 신뢰 파괴 |
| 10 | **Western-pundit mimic** | "Just like Arthur Hayes says…" | 본인 목소리 없음 |

---

## 섹션 4: Frame 템플릿 12개

> 편집장의 첫 질문: "이 글은 Frame 1~12 중 어디에 속하는가?"
> 답이 안 나오면 쓸 가치가 없는 소재다.

### Frame 1 — Power Fight (권력 다툼)
**구조**: [Actor A] vs [Actor B] over [specific resource/rule]. Whoever wins controls [downstream consequence].
**언제**: 규제기관·거래소·정당·대기업·은행 사이의 감독권·지분·정책 대립
**한국 적용 예시**: "FSC vs BOK over KRW stablecoin issuance rights. Whoever wins sets the KRW on-ramp for the next decade."
**레퍼런스**: @nic__carter "Operation Choke Point 2.0"

### Frame 2 — Timeline Collapse (가설 → 가동)
**구조**: In [year], X was a thesis. Today it is the operating condition. Here's the step that flipped it.
**언제**: "언제 일어날까"가 "지금 일어났다"로 바뀌는 순간
**한국 적용 예시**: "In 2023, KRW stablecoin issuance was a whitepaper. Today KakaoBank filed the first commercial blueprint."
**레퍼런스**: @LynAldenContact "Nothing stops this train"

### Frame 3 — Signal vs Noise (서구 오독 vs 한국 실제)
**구조**: Western desks are reading [wrong frame]. Korean primary source actually says [right frame]. The gap matters because [implication].
**언제**: 글로벌이 오해 중인 한국 뉴스 / 과대·과소평가된 데이터
**한국 적용 예시**: "Western desks called Upbit's VASP renewal a win. The actual order excludes buy/sell/exchange — only custody and brokerage survived."
**레퍼런스**: @WuBlockchain Asia regulatory exclusives

### Frame 4 — Compounding Bet (누적 구조)
**구조**: Alone, [event] is trivial. Stacked against [prior events], it's the Nth data point of a [structural shift].
**언제**: 하나의 이벤트가 12~24개월 뒤 무엇을 만드는지 구조적으로 쌓이는 소재
**한국 적용 예시**: "Alone, Hanwha Life buying 50 BTC is noise. Stacked with NPS allocation, KB custody trial, and Samsung SDS pilot — Korea's institutional on-ramp is forming."
**레퍼런스**: @WuBlockchain MicroStrategy accumulation threads

### Frame 5 — Plumbing Reveal (후드 아래 메커닉)
**구조**: Price/policy did X. The reason isn't narrative — it's [specific settlement/reserve/facility mechanic].
**언제**: 시장이 "왜"를 틀리게 읽고 있을 때
**한국 적용 예시**: "USDT premium on Upbit isn't retail sentiment. It's the BOK FX swap line capacity x KRW custody rule creating a one-way valve."
**레퍼런스**: @CryptoHayes "Exchange Stabilization Fund" mechanics

### Frame 6 — Regime Change (옛 규칙이 깨졌다)
**구조**: The rule for [prior era] was [X]. That rule no longer binds because [mechanism]. Assets priced under the old rule will reprice.
**언제**: 법·정책·구조가 바뀌어 과거 플레이북이 틀려지는 순간
**한국 적용 예시**: "The rule was: crypto gains are tax-free in Korea. That rule ends Jan 2027. Every KR retail holding decision made before that date is now mispriced."
**레퍼런스**: @LynAldenContact fiscal dominance framing

### Frame 7 — Incentive Reveal (돈을 따라가라)
**구조**: Everyone is debating [stated reason]. Look at who gets paid if [policy/design] passes. That's the actual driver.
**언제**: 공식 이유와 실제 인센티브 구조가 다를 때
**한국 적용 예시**: "Everyone's debating investor protection. Track who captures listing-slot monopoly rent after the new VASP rule. That's the actual fight."
**레퍼런스**: @hasufl MEV-as-health-indicator; Matt Levine "everything is securities fraud"

### Frame 8 — Historical Rhyme (전례)
**구조**: This looks new. It is a near-copy of [prior episode]. The resolution then was [Y]; the relevant difference now is [Z].
**언제**: 현재 이벤트가 과거 패턴을 반복할 때
**한국 적용 예시**: "FSC's 2024 enforcement playbook is the 2018 ICO ban rerun — same choke point (real-name accounts), different asset class. Resolution then: 18 months to partial re-open."
**레퍼런스**: @nic__carter Operation Choke Point 1.0 → 2.0

### Frame 9 — Counter-positioning (컨센서스가 틀렸다)
**구조**: Consensus says [X]. The position, flow, or policy data says [Y]. Therefore [trade/thesis].
**언제**: 시장·미디어 컨센서스와 실제 데이터가 어긋날 때
**한국 적용 예시**: "Consensus: Korean ETF approval is 2026 H1. Policy data: futures market missing, index undefined, bank custody untested. Desk call: 2027 Q1 earliest."
**레퍼런스**: @CryptoHayes "I think we are more likely to go down to $70k–75k"

### Frame 10 — Aggregation / Disaggregation
**구조**: [Incumbent] controlled [supply/distribution]. [New actor] now owns the user relationship, commoditizing the old moat.
**언제**: 플랫폼·앱·프로토콜이 기존 강자를 disintermediate할 때
**한국 적용 예시**: "Banks issue KRW stablecoins (supply). KakaoPay/Toss/Naver Pay own the user relationship (aggregation). Banks become the commodity layer."
**레퍼런스**: Ben Thompson Aggregation Theory (stratechery.com)

### Frame 11 — Insider Flow (실제로 누가 움직이나)
**구조**: Headline says [X]. On-chain/exchange/filing data shows [specific cohort] is doing [Y]. The market hasn't priced this.
**언제**: 헤드라인과 실제 포지션이 다를 때
**한국 적용 예시**: "Headline: Korean retail is bearish. DART filing: 3 mid-cap Korean listed companies quietly added BTC to treasury Q1. Market hasn't noticed."
**레퍼런스**: @WClementeIII whale cohort threads

### Frame 12 — Stakes Escalation (이번엔 다른 이유)
**구조**: Past [event class] was contained because [condition A]. This one isn't because [condition A has broken / condition B is new].
**언제**: 비슷해 보이지만 이번엔 진짜 다를 때
**한국 적용 예시**: "Past KR exchange failures were contained by deposit insurance. This time VAUPA explicitly excludes crypto-linked accounts. The floor is gone."
**레퍼런스**: @nic__carter "biggest challenge to financial stability since 2008"

---

## 섹션 5: Hook 패턴 + Ending 규칙

### 5.1 훅 10대 메타-패턴

1. **ALL-CAPS STATUS TAG 선두** — "SCOOP:", "BREAKING:", "JUST IN:" 신뢰 flare. Wu 표준.
2. **Named-source 단일 문장** — "multiple sources confirmed to @sskorea02" > "sources say"
3. **Proprietary 라벨 소유** — "Seoul Premium", "Han River close", "Kimchi Tape" — 어휘 소유 = 담론 소유
4. **첫 문장에 hero number 하나** — ₩60T, $1.44B, +3.8% premium, -31.3% volume
5. **Self-deprecating de-escalation** — "I rarely flag this as BREAKING, but—"
6. **Skin-in-the-game 공개** — "The desk is long KR-L1 exposure."
7. **Historical analog + 명시적 비율** — "20x the COVID collapse"
8. **Contrarian inversion을 1번 문장에서** — "Everyone is bullish. Here's what the DART filing says."
9. **첫 7 words에 shock 압축** — 이후 문장은 evidence
10. **이모지·해시태그는 first line 금지**

### 5.2 한국 크립토용 Hook 템플릿 5개

Template A — SCOOP
"SCOOP: According to [FSC/DAXA/Upbit] sources confirmed
to @sskorea02, [Korean exchange] has [action] — the first
[category] move in Korea since [anchor date]."

Template B — BREAKING + named bill
"BREAKING: South Korea's National Assembly just
[passed/tabled] the [Bill Name] — the first [descriptor]
legislation in Asia to [specific provision]."

Template C — Won-denominated data shock
"Korean retail liquidated ₩[X]B in 24 hours —
[Y]x the [benchmark event]. Here's what broke."

Template D — Nobody + Korea specific datapoint
"Nobody is talking about this, but Korean [Upbit dominance /
KRW stablecoin volume] is now at levels last seen before
the 2018 ICO ban."

Template E — Contrarian + desk stake
"Everyone in Seoul is bullish on [asset].
Here's why @sskorea02 desk is positioned the opposite. 🧵"

### 5.3 Strong Ending 8원칙

1. **숫자·날짜·명명된 레벨로 닫는다** — 감정 아닌 specifics
2. **다음 글을 pre-load** — "Tomorrow: why the FSC memo moves the bottleneck to banks."
3. **Invalidation signal 명시** — "If Upbit net outflows turn positive this week, thesis dead."
4. **Branded recurring close** — "— Seoul desk, out." / "Han River closes. We reopen Tuesday."
5. **Callback to hook** — 강한 엔딩은 오프닝 표현을 새로운 의미로 반복
6. **포지션 공개를 last line으로** — Stake > Conclusion
7. **마지막 문장에서 헷지 제거** — "possibly" / "may" 삭제
8. **URL·해시태그·🧵·subscribe CTA로 끝내지 않는다** — 그건 footer지 ending이 아님

### 5.4 Ending 금지 목록

단독으로 last line이 되는 것들:
- "Stay tuned"
- "Only time will tell"
- "What do you think? 👀"
- "DYOR / NFA"
- "Feel free to share your thoughts"
- "Hope you found this helpful"
- 원시 URL 단독
- 해시태그 묶음 단독
- 🧵 이모지 단독

### 5.5 한국 맥락 Ending 템플릿 5개

Ending A — Basis-watch forcing
"Watch KRW/BTC basis when Seoul opens Monday 09:00 KST —
if kimchi premium stays above 3%, institutional arb confirms."

Ending B — Desk call
"Desk call: BTC holds ₩150M through FOMC week.
Break below — selling into Asia open, not NY close."

Ending C — Regulator callback
"I said FSC was the bottleneck. After today's VASP memo,
the bottleneck moved to the banks. [end]"

Ending D — On-chain receipts
"Upbit net outflows: −2,841 BTC this week.
Bithumb stablecoin inflows: +$48M.
Korean retail is repositioning, not capitulating."

Ending E — Branded close
"That's the tape. Han River closes.
We reopen Tuesday. — Seoul desk, out."

---

## 섹션 6: Signature Series 5개 요약

> 상세 스펙은 series/SERIES_SPEC.md 참조.
> 여기서는 포지셔닝과 Frame 연결만 명시.

| 시리즈 | 주기 | KST | 기본 Frame | 1차 소스 |
|---|---|---|---|---|
| **The Kimchi Tape** | 일간 | 09:00 | Signal vs Noise | Upbit / Bithumb |
| **FSC Watch** | 주간 (일) | 20:00 | Power Fight | 금감원·금융위·국회 |
| **Han River Flows** | 일간 | 22:00 | Insider Flow | Upbit / CryptoQuant |
| **K-Retail Pulse** | 주간 (금) | 18:00 | Signal vs Noise | Naver DataLab / Upbit |
| **Seoul Stack** | 격주 | 수시 | Compounding Bet | DART / KRX / 백서 |

---

## 섹션 7: 버전 관리 규칙

### v1 → v2 변경 절차

1. PR 생성 — 변경 이유 3줄 이상 명시
2. 변경 항목이 금지 톤·3-Test Gate·Frame 템플릿 중 하나라면
   운영자 최종 승인 필수
3. 변경 이력은 이 파일 하단에 append

### 변경 이력

| 버전 | 날짜 | 변경 내용 |
|---|---|---|
| v1.0 | 2026-04-22 | 최초 작성 |

---

*Editorial Constitution v1.0 완료*
*기준 리서치: "역공학된 편집 헌법" (2026-04-22)*
*다음 리뷰: 2026-07-22 또는 팔로워 100K 도달 시 중 빠른 것*
