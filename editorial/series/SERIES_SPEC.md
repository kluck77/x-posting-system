# Signature Series Spec
# 계정: @sskorea02
# 버전: v1.0 | 2026-04-22
# 참조: editorial/CONSTITUTION.md 섹션 6
# 용도: 5개 시리즈의 운영 스펙 단일 문서. 포스트 작성 전 해당 시리즈 섹션 확인 필수.

---

## 시리즈 1: The Kimchi Tape

**포지셔닝**: 한국 거래소 BTC/ETH/스테이블코인 프리미엄을 영어권에 전달하는
유일한 일간 브리프. 30초 habit formation 목표.

**발행 주기**: 매일
**발행 시각**: 09:00 KST (Upbit 전일 마감 데이터 반영)
**평균 길이**: 단문 1개 + 차트 1장. 280자 이내.
**기본 Frame**: Signal vs Noise (Frame 3)

**Hook 고정 템플릿**:


🇰🇷 Kimchi Tape | [DATE KST]
BTC premium: [+/−X.X%] | ETH: [+/−X.X%] | Top outlier: $[TICKER] [+/−XX%] vs Binance


**Ending 고정 템플릿**:


Flow direction: [KRW→USD | USD→KRW | Neutral].
Tomorrow’s watch: [catalyst or date].
Data: Upbit / Bithumb / Binance.


**필수 1차 소스**:
- Upbit 실시간 호가 (upbit.com)
- Bithumb 실시간 호가 (bithumb.com)
- Binance 글로벌 기준가 (binance.com)

**필요 데이터 소스**:
- CryptoQuant KRW premium indicator
- Upbit WebSocket (무료)
- Bithumb WebSocket (무료)

**발행 전 체크리스트**:
- [ ] 날짜·시각 KST 명시
- [ ] BTC·ETH 프리미엄 수치 소수점 1자리
- [ ] Top outlier 1개 이상 명시
- [ ] Flow direction 판단 포함
- [ ] 차트 또는 스크린샷 첨부

**수익화 연결 경로**:
무료 daily thread → 유료 Beehiiv/Stibee ($19/mo)
역사적 basis 데이터 + 아비트라지 알림 포함.
KR 거래소·FX 핀테크 스폰서 슬롯 (월 1회).

---

## 시리즈 2: FSC Watch

**포지셔닝**: 한국 금융·크립토 정책을 영어권에 구조화해 전달하는
유일한 주간 트래커. Tiger Research보다 빠르고, 기관 tone 없음.

**발행 주기**: 매주
**발행 시각**: 일요일 20:00 KST
**평균 길이**: 스레드 5~7개 트윗. X Article 병행 권장.
**기본 Frame**: Power Fight (Frame 1)

**Hook 고정 템플릿**:


FSC Watch | Week [N] — [1-line verdict on the week].
3 things that moved. 2 things to watch. 1 number.


**Ending 고정 템플릿**:


Next week’s calendar: [date + event].
Bill tracker: [National Assembly link].
— FSC Watch, Seoul desk.


**필수 1차 소스**:
- 금융위원회 보도자료 (fsc.go.kr)
- 금융감독원 보도자료 (fss.or.kr)
- 국회의안정보시스템 (likms.assembly.go.kr)
- FIU 가상자산사업자 갱신 현황

**필요 데이터 소스**:
- 국회 의안정보시스템 Open API
- 금감원 RSS
- DAXA 자율규제 공지 (daxa.co.kr)

**발행 전 체크리스트**:
- [ ] 주간 번호(Week N) 일관성 확인
- [ ] 3 things / 2 things / 1 number 구조 준수
- [ ] 모든 법안명 정식 명칭 사용
- [ ] National Assembly 링크 유효 확인
- [ ] Frame 1 (Power Fight) 적용 여부 확인

**수익화 연결 경로**:
무료 weekly → FSC Watch Pro ($49/mo)
법안 영문 원문 + 로비맵 + 월간 브리핑 콜.
엔터프라이즈 ($499/mo) 기관 맞춤 리포트.

---

## 시리즈 3: Han River Flows

**포지셔닝**: 한국 거래소 일간 볼륨·플로우를 온체인 데이터와 연결해
영어권에 전달. WuBlockchain의 한국 버전.

**발행 주기**: 매일
**발행 시각**: 22:00 KST (한국장 마감 후)
**평균 길이**: 단문 1개 + 표 또는 차트 1장. 280자 이내.
**기본 Frame**: Insider Flow (Frame 11)

**Hook 고정 템플릿**:


Han River Flows | [DATE KST]
KRW volume: ₩[X.X]T ([+/−X%] d/d)
Top 3 on Upbit: $[A] $[B] $[C]
Unusual: $[X] ([+/−XXX%] vs 30D avg)


**Ending 고정 템플릿**:


Net KRW stablecoin flow: [+/−₩Xb].
Retail tilt: [risk-on | risk-off | neutral].
Sources: Upbit / Bithumb / CryptoQuant.


**필수 1차 소스**:
- Upbit 거래량 (upbit.com/service-center/notice)
- Bithumb 거래량 (bithumb.com)
- CryptoQuant KRW exchange flow

**필요 데이터 소스**:
- Upbit WebSocket
- Bithumb API
- CryptoQuant free tier
- DefiLlama (스테이블코인 flow)

**발행 전 체크리스트**:
- [ ] 날짜·시각 KST 명시
- [ ] 전일 대비 % 변화 포함
- [ ] Top 3 티커 명시
- [ ] Unusual mover 1개 이상
- [ ] 스테이블코인 net flow 방향 포함

**수익화 연결 경로**:
무료 daily thread → 유료 대시보드 ($29/mo)
분단위 flow + 고래 지갑 + 언락 × KR 상장 캘린더.

---

## 시리즈 4: K-Retail Pulse

**포지셔닝**: 한국 개인투자자 심리·포지셔닝 지표를
영어권 매크로 오디언스에게 전달하는 주간 인덱스.
글로벌 Fear & Greed의 한국 특화 버전.

**발행 주기**: 매주
**발행 시각**: 금요일 18:00 KST
**평균 길이**: 스레드 3~5개 트윗.
**기본 Frame**: Signal vs Noise (Frame 3)

**Hook 고정 템플릿**:


K-Retail Pulse | Week [N]
Index: [XX] (prev [XX])
Mood: [Greed 🔥 | Warming | Neutral | Cooling | Fear ❄️]


**Ending 고정 템플릿**:


Leading indicator watch: [Naver search trend / Upbit new-listing premium / KakaoTalk group signal].
Next pulse: [date].
— K-Retail Pulse.


**필수 1차 소스**:
- Naver DataLab 검색트렌드 API (datalab.naver.com)
- Upbit 신규 상장 프리미엄
- Upbit 거래량 구성 (알트 비중)

**필요 데이터 소스**:
- Naver DataLab Open API (무료)
- CryptoQuant Korea-specific indicators
- Upbit WebSocket

**발행 전 체크리스트**:
- [ ] 주간 번호(Week N) 일관성 확인
- [ ] 인덱스 수치 전주 대비 명시
- [ ] Mood 라벨 5단계 중 하나 선택
- [ ] Leading indicator 3개 중 최소 1개 데이터 포함
- [ ] 다음 발행일 명시

**수익화 연결 경로**:
무료 weekly index → 유료 리포트 ($39/mo)
컴포넌트 데이터 + 커스텀 알림.
익명화 데이터 기관 판매 ($2K/mo).

---

## 시리즈 5: Seoul Stack

**포지셔닝**: 한국발 L1·L2·토큰 프로젝트의 구조화된 영어 트래커.
Klaytn→Kaia, WEMIX, XPLA, Story Protocol, Delabs 등.
한국 VC·거래소·상장 경로까지 포함.

**발행 주기**: 격주 (수시 breaking 추가 가능)
**발행 시각**: 수요일 21:00 KST (격주)
**평균 길이**: X Article (롱폼) + 요약 스레드 3~5개 트윗.
**기본 Frame**: Compounding Bet (Frame 4)

**Hook 고정 템플릿**:


Seoul Stack #[N] | [Project Name]
Built in: [city]. Raised: $[X]. TGE: [date or TBD].
Listing path: [CEX name or TBD]. Verdict: [1-line thesis].


**Ending 고정 템플릿**:


Three questions we’re watching:
	1.	[question]
	2.	[question]
	3.	[question]
Next launch: [project + estimated date].
— Seoul Stack.


**필수 1차 소스**:
- DART 투자 공시 (dart.fss.or.kr)
- KRX 신규 상장 공시
- 프로젝트 공식 백서 / GitHub
- 한국 VC 포트폴리오 공개 페이지 (Hashed, Kakao Ventures, Korea Investment Partners)

**필요 데이터 소스**:
- Open DART API
- KRX OpenAPI
- DefiLlama TVL
- CoinGecko Pro (토큰 메트릭)

**발행 전 체크리스트**:
- [ ] 시리즈 번호(#N) 일관성 확인
- [ ] 자금 조달 금액 DART 또는 공식 발표 출처 확인
- [ ] TGE 날짜 또는 "TBD" 명시
- [ ] 상장 경로 확인 (CEX명 또는 "미확인")
- [ ] Three questions 3개 모두 작성
- [ ] 다음 프로젝트 예고 포함

**수익화 연결 경로**:
무료 격주 → Seoul Stack Pro ($29/mo)
캡테이블 + 베스팅 스케줄 + KR 거래소 상장 확률 점수.
Hashed·Animoca Korea·카카오벤처스 스폰서 슬롯.

---

*Series Spec v1.0 완료*
*기준 문서: editorial/CONSTITUTION.md 섹션 6*
*다음 리뷰: 2026-07-22 또는 팔로워 100K 도달 시 중 빠른 것*
