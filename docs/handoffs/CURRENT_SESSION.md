# Current Session — 2026-04-07 (Session 33)

## S33 — 마감 디테일: 탭 UX + 밀도 압축

`static/dashboard.html` 프론트만. 백엔드/승인 워크플로 무변경.

### 변경 내용
1. **탭 스크롤 메모리** — `.hud-main` scroller 기준
   - 탭별 scrollTop Map {home/ai/intake/ops} 지속 저장
   - scroll 이벤트 passive 리스너로 currentPage 위치 계속 반영
   - 탭 버튼 cloneNode 로 기존 리스너 제거 후 S33 핸들러 설치
   - 다른 탭 전환: 이전 위치 저장 → 새 탭 활성화 → rAF 후 setScrollTop(저장값)
   - 동일 탭 재클릭: 해당 탭 위치 0 으로 리셋 (scroll-to-top)
   - 모바일 Safari: `-webkit-overflow-scrolling:touch` (.hud-main) 유지, rAF 타이밍으로 레이아웃 확정 후 복원
2. **Home 압축**
   - sb-cell padding 10/12 → 7/10, min-height 제거, sb-v 18→15px
   - sb-grid gap 10→7px, margin-bottom 10→7px
   - 칩 줄 CSS `order` 로 우선순위 재정렬: 승인대기/병목 내장 → premium(3) → b2b(4) → weekly(5) → cta(6) → newsletter(7) → lead(8)
   - panel-hero head 12/16 → 9/14, body 10/14 → 8/12
   - hl-row padding 8/10 → 6/9, gap 6→4
   - kpi-mini 8/10 → 6/9, k-val 16→14px
   - hero-compact 8/12 → 6/10
   - #page-home gap 12→9px
3. **AI 스테이션 2열 실무형 압축**
   - workflow rail 전체 제거: `#ws-grid.v28::before/after` display:none, 카드 사이 `::before` ▾ 제거
   - ws28-step: absolute → static, 22px 첫 컬럼에 flat 9px 라벨로만
   - grid: `22px 80px 1fr 104px` + column-gap 10px, padding 9/10
   - ws28-icon 100×74 → 80×56
   - ws28-role 13→12, ws28-status 11→10, ws28-prov 10→9
   - ws28-b padding 6/10 → 4/8, gap 3→1, ln 11→10.5 (next 9.5)
   - ws28-c runs 24→20, strip 14→11px
   - 모바일: 3-col + ws28-c 전폭 (row flex) + icon 70×50
4. **AI 팀 오버뷰 압축**
   - tov 패딩 12/14 → 9/12, head margin 10→7
   - tov-stat 9/11 → 6/10, v 17→14 (busy/bot 14→12)
   - tov-flow padding 8/10 → 5/8, tf-node 4/8 → 2/6 (10px)
   - tov-dotmap padding 8/10 → 5/8, gap 4→3, dots 높이 6→5
5. **Intake 압축**
   - ifn 패딩 12/14 → 9/12, stage 9/11 → 6/10, v 20→17
   - flow-wrap gap 10→7, lane padding → 8/10
   - lane-phrase 11→10.5, bar-row 10px + padding 2/0
6. **Ops 압축**
   - opsr 패딩 12/14 → 9/12, c 9/11 → 6/10, v 18→15
   - opsr-cat 4/9 → 2/7 (10px)
   - ops-summary .s26 cell 8/10 → 6/10, val 22→17
   - ops-card padding-top 8, ops-head 11px, big 16px
   - ops-row margin 6→4, pill 10→9.5 (1/5 padding)
   - ops-mini-item 3/6 → 2/6, 9.5px
7. **공통**
   - ws-header padding 9/12, 11px, margin-bottom 8
   - 모든 반투명도/색 토큰 유지, glow/neon 재도입 없음

### Files
- `static/dashboard.html` — S33 script (tab scroll memory + chip order hook) + S33 style (compression overrides)
- `docs/handoffs/CURRENT_SESSION.md` / `LATEST_STATUS.md`

---

# Previous — Session 32

## S32 — Intake 흐름 / Ops 요약 역할 분리

`static/dashboard.html` Intake + Ops 탭만 수정. 백엔드 무변경.

### 변경 내용
1. **Intake = "정보 흐름"** — `#intake-flow-narrative` 주입 (ws-header 아래)
   - 4 stage 가로 strip: 01 수집 › 02 자산화 › 03 수익화 후보 › 04 연결
   - 각 stage: 라벨(9px) + 큰 mono 숫자(20px) + sub 문구
   - active 단계 (마지막 non-zero) 좌측 2px accent rule
   - dim 단계 opacity 0.55, 좌측 rule 회색
   - sub 문구 예: "3 발행 · 2 대기", "뉴스레터 5 · 리드 3", "수집 대기 중"
   - 5s linear pulse rail (하단 1px accent 그라디언트) — 정보 흐름 힌트
   - S26 lane 블록은 하위 세부용으로 유지
2. **Ops = "운영 요약"** — `#ops-readiness` 주입 (ops-summary 아래)
   - 3-count 요약: 준비 / 대기 / 비어있음 (6개 카테고리 집계)
   - 좌측 2px color rule (ok / warn / txt3)
   - 하단 6 category chip row: premium / brief / b2b / 뉴스레터·리드 / 주간 / CTA
     · is-ready (top 있음 또는 notable 있음) · is-wait · is-empty
     · 각 chip: 상태 dot + 라벨 + 숫자 + 상태어(준비/대기/비어있음)
   - ops-summary 기존 3-cell (총 후보/발행 준비/주간 누적) 은 유지
3. **역할 구분 명확화**
   - Intake : stage 4 + pulse rail = 시간/전환 느낌
   - Ops    : readiness count + category chip = 상태/판단 느낌
4. **Empty state** — S26 compact dashed 박스 + 한국어 2줄 구조 유지
   - 프리미엄/브리프/B2B/뉴스레터·리드/주간/CTA 모두 "없음 + 다음 상태 암시"
5. **Micro-visual**
   - tiny pulse rail (intake narrative 하단)
   - mini ratio bar (S26 lane 유지)
   - signal bars (S26 ops head 유지)
   - activity dots (S31 dotmap — AI 탭 유지)
   - category chip dot (opsr-cat)

### Files
- `static/dashboard.html` — S32 script (renderIntake/renderOps wrap) + S32 style
- `docs/handoffs/CURRENT_SESSION.md` / `LATEST_STATUS.md`

---

# Previous — Session 31

## S31 — AI 탭: 팀 오버뷰 패널 상단 도입

`static/dashboard.html` AI 탭만 수정. 백엔드/다른 탭 무변경.

### 변경 내용
1. `#page-ai` 상단에 `#team-overview` 신규 주입 (ws-header 바로 아래, ws-grid 위)
2. **3-stat 그리드**: 오늘 총 실행 / 가장 바쁨 / 병목
   - 총 실행: mono tnum 큰 숫자 + "가동 N/5 · 미설정 K" sub
   - 가장 바쁨: 역할명 + "N회 · provider"
   - 병목: unconfigured 우선 > 제일 적게 돈 역할(대기) > 편중 가능성 감지
3. **tov-flow**: 5 노드 workflow strip — step(01..05) · 이름 · 오늘 실행 수
   - on/busy/bot/off 4 상태 구분 (busy=accent shadow, bot=warn dashed, off=opacity 0.45)
   - 노드 사이에 › 구분자, 중앙 flex-wrap 허용
4. **tov-dotmap**: 역할별 12-cell mini activity row
   - 이름(84px) + 도트(flex) + 숫자(28px)
   - on 셀은 accent 0.7, off 는 dashed 4px, 마지막 on 셀이 1.8s soft tick
   - 전역 최대치 기준 정규화 → 역할 간 상대 부하 비교 가능
5. 기존 S28 ws-grid 5 스테이션은 그대로 유지 (renderAI 원본 호출 후 overview만 populate)

### Files
- `static/dashboard.html` — S31 script (renderAI wrap · ensureOverview) + S31 style
- `docs/handoffs/CURRENT_SESSION.md` / `LATEST_STATUS.md`

---

# Previous — Session 30

## S30 — Home 전용 재편: 회사 메인 상황판 + 주간 핵심 승격

`static/dashboard.html` Home 탭만 수정. 백엔드/다른 탭 무변경.

### 변경 내용
1. **Home 레이아웃 재정의** (`#page-home` flex column + order)
   - order 1: Situation Board (S29 판단판)
   - order 2: 이번 주 핵심 (panel-hero 승격)
   - order 3: KPI chip strip (thin)
   - order 4: hero-compact (dashed 1줄 요약으로 완전 demote)
   - hidden: `.focus-3`, `.strip` (situation board 와 중복)
2. **Hero 포스터 제거**
   - hero-compact → 8×12 padding, 12px label, meta 10px inline, dashed border
   - "시스템 상태" 라벨은 tiny uppercase hint 로
3. **Weekly highlights 승격** — Home 핵심 영역으로
   - panel-head 에 "이번 주 핵심" 큰 타이틀 + tiny 건수 라벨
   - hl-list 를 grid row 로 재설계: rank(01) / #id / hook / monetization bar + score
   - 기존 hl-bar 는 3px mini ratio bar 로 교체 (accent 70% opacity)
   - 빈 상태 2종: "이번 주 하이라이트 없음 · 자동 누적" / "대기 중 N건 · 발행 후 승격"
4. **KPI row 축소**
   - kpi-mini 를 thin chip row 로: label(9px uppercase) + 16px 값 + tiny sub
   - 큰 숫자판 사라지고 "판단 문장 → 보조 수치" 위계로
5. **고양이 상태머신 재작성**
   - healthy (lucky-pulse): s30CatPulse 3.4s + s30Tail 3s + s30Blink 5s
   - coin-rush: s30Coin 1.1s (premium/b2b 있을 때)
   - lean-weekly: translateX(-6px) rotate(-3deg) 주간 하이라이트 쪽으로
   - warning: 전체 애니메이션 off, ear-twitch-L/R 만 3.6s 저빈도
   - alert/danger: grayscale 0.85 + brightness 0.65, scale 0.65, 모든 animation none
   - panel-hero 우상단 절대 위치 · pointer-events none · 데이터 가림 금지
   - 랜덤 순찰 없음, refreshAll 사이클에서만 상태 재평가
6. **모바일 꽉 채움**
   - sb-grid 1열, sb-cell min-height 제거
   - hl-row 2단 grid (score-wrap 전체폭)
   - kpi-mini 2-col flex
   - cat scale 0.55 로 축소, 별도 s30CatPulseSm 키프레임

### Files
- `static/dashboard.html` — S30 script (renderHome wrap · weekly rewrite) + S30 style
- `docs/handoffs/CURRENT_SESSION.md` / `LATEST_STATUS.md`

---

# Previous — Session 29

## S29 — 방향 고정 · Situation Board + 톤 리셋

`static/dashboard.html` 단일 파일 프론트 수정. 백엔드/승인 워크플로 무변경.

### 목표
대시보드를 "게임 HUD" 가 아닌 **AI 회사 내부 운영툴** 로 고정. 숫자판이 아닌 **판단판(judgment panel)** 중심.

### 변경 내용
1. **Situation Board** (`#situation-board`) 을 Home 최상단에 신규 도입
   - 3-cell judgment panel: 지금 중요한 것 / 병목 / 바쁜 담당
   - 6-chip business summary row: premium · b2b · newsletter · lead · CTA 연결 · 주간 하이라이트
   - 각 cell 좌측 2px state bar (accent/warn/cat-brief), sub line 으로 근거 1줄
   - sb-stamp: HH:MM KST 기준 시간
2. **판단 로직**
   - Now: db_ok=false → 채널 미설정 → pending≥3 → premium≥3 → idle → published>0 → 정상
   - 병목: DB > 승인 큐 > CTA 미연결 > 초안 대기 > 품질 게이트 > 초안 없음
   - 바쁜 담당: AI runs_today 최상위 + 가동 N/5 · 오늘 M회
3. **전체 톤 리셋**
   - body font-family: system-ui 계열
   - 숫자 전용 mono tabular (ui-monospace, tnum)
   - body::before/::after, hud-corners, grid-overlay, scan-overlay 모두 display:none
   - panel/kpi/card radial glow, text-shadow, box-shadow 전부 제거
4. **탭 계층화**
   - Home primary, 나머지 secondary (txt3), 아이콘 opacity 0.55 → 활성 1
5. **색 역할 체계 명확화**
   - 상태색: sb-v tone-ok/warn/danger/accent/idle, .ws28-status dot — 실제 상태에만
   - 카테고리색: ops-card 좌측 2px border-left 힌트로만 (fill 제거)
   - 배경/패널/텍스트/강조 토큰은 S23 값 유지
6. **기존 hero-compact demote**
   - dashed border, 패딩 축소, label 14px, title opacity 0.6 — 보조 상태 카드로

### Files
- `static/dashboard.html` — S29 script (renderHome wrap + situation board 주입) + S29 style
- `docs/handoffs/CURRENT_SESSION.md` (이 파일)
- `docs/handoffs/LATEST_STATUS.md`

---

# Previous Session (Session 25)

## S25 — AI 탭 협업/스테이션 감각 강화

`static/dashboard.html` 단일 파일. 백엔드/스키마/승인 흐름 변경 없음.

### 변경 내용
1. **ws-header 협업 요약** (`#ws-collab`): `협업 · 가동 N/5 · 총 M회 · 주도 {role}` — 5 노드가 한 팀처럼 보이도록 헤더에 집계 배지 추가
2. **역할별 파이프 마이크로 트레이스** (`.ws-pipe`): 각 카드 하단에 3단계 점선 구분 스테이지
   - DW: 소스 › 초안 › 검토 대기
   - RV: 초안 › 5기준 › 통과·재작성
   - RS: 주제 › 수집 › 컨텍스트
   - FC: 주장 › 대조 › 검증 결과
   - TH: 피드 › 신호 › 알림
   - 상태: wait(빈 점선) / live(accent 글로우 펄스) / done(채운 회색) / off(dashed 흐림)
3. **문장으로 역할 구분**: 기존 statusActive2/statusIdle2/roleTask/lastLine 유지 — 카드는 모양(아이콘)·문장(상태/담당)·상태(파이프)로 차별화, 색은 좌측 3px 힌트만
4. **micro-visual**: live 스테이지 dot 1.8s 부드러운 펄스(prefers-reduced-motion 존중), 8-bar activity strip 유지

### Files
- `static/dashboard.html` — ws-header collab span, renderAI pipe/collab 로직, S25 CSS 블록
- `docs/handoffs/CURRENT_SESSION.md` / `LATEST_STATUS.md`

---

# Previous — Session 22

## What Was Done This Session

### Dashboard S22 — Quiet internal tool mode (direction shift)

게임풍 HUD → **조용한 AI 회사 내부 운영툴**. 백엔드/승인 워크플로/테스트 변경 없음. `static/dashboard.html` 단일 파일 CSS 오버라이드 블록(S22 reset HUD) 추가.

### 실제 제거한 HUD 요소
1. 전역 배경 grid + scanline (`body::before/::after` display:none)
2. 모든 L자 코너 장식: `.panel/.kpi/.ops-card/.ws-node/.lane::before::after` + `.hero-corner`
3. Hero signal bar (`.signal` 4-bar 애니메이션)
4. 탭 활성 글로우 + underline box-shadow + ic drop-shadow
5. panel-hero accent 인셋 글로우 + hero state label text-shadow + 헤더 dot pulse 애니메이션
6. flow-wrap 세로 그라디언트 rail + 흐르는 pulse dot
7. stage-dot, worker-rail, ws-status blink, bar-row glow, lucky-pulse glow

### 타이포 체계
- 본문: `-apple-system/SF Pro Text/Inter/Pretendard/system-ui` · base 14px
- 숫자 전용 mono tabular: `.num, .k-val, runs, ops-head .big, lane num, strip val, hero label, hero-summary b, ops-summary val, clock`
- KPI 46→40px/700/-0.8px, hero state 38→30px/700/-0.3px, ops big 30→24px/700

### 패널 스타일
- 모든 컨테이너 단색 `var(--panel)` + 1px `var(--line)` + **좌측 3px 카테고리 accent bar** 로 통일
- radius 2px (뾰족함 살짝 완화), box-shadow 제거, 그라디언트 배경 제거
- panel-head: accent 대신 `var(--txt)` 텍스트 + 앞 6px 사각 accent dot
- ws-header/ops-summary/attn-band 도 같은 패턴

### 상태색 vs 카테고리색 분리
- **상태색(ok/warn/danger)** 은 진짜 상태에만:
  - hero state label ok/warn (db 정상/점검)
  - attention band danger/warn/idle
  - state-chip ready(ok)/wait(warn)/empty(neutral)
  - 헤더 상태 dot (ok)
- **카테고리색(cat-premium/brief/b2b/news/weekly/cta)** 은 섹션 식별에만:
  - 좌측 3px bar (KPI/strip/ops-card/lane/ws-node)
  - KPI 프리미엄/B2B 숫자 색
  - lane bar fill, ops-mini-item 보더
- **accent(브랜드)** 는 주 패널/탭 언더라인/패널 head dot/attention band bar 에만

### 카드 반복감 완화
- KPI/strip/ws-node: 좌측 bar 색 차이로 구분 (카테고리 또는 line2)
- Ops 6 카드: 상단 색 띠 제거, 좌측 bar 색만 다름
- 여백 일관화 (panel margin 12, ws/flow/ops gap 8)

## Files Changed

| File | Change |
|------|--------|
| `static/dashboard.html` | S22 quiet reset 블록(~200 lines) append |
| `docs/handoffs/CURRENT_SESSION.md` | 이 파일 |
| `docs/handoffs/LATEST_STATUS.md` | S22 entry |

## Branches
- `claude/extract-prediction-time-n82UK`
- `claude/premium-control-room-ui-LJFba`

양 브랜치 sync.
