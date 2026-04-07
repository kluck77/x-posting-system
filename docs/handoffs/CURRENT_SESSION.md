# Current Session — 2026-04-07 (Session 30)

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
