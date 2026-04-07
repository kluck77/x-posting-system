# Current Session — 2026-04-07 (Session 36)

## S36 — Home + AI 디테일 폴리싱 (마감)

`static/dashboard.html` 프론트만. 새 구조/기능 추가 없음. 정렬·간격·타이포·시각 리듬만 다듬음.

### 1) Home 하이라이트 헤더 버그 — "이번" 세로 깨짐
- **원인**: S30 의 `#page-home .panel-hero .panel-head { font-size:0 }` 트릭이 원본 텍스트 노드 "이번 주 하이라이트" 를 죽이고 `::before content:'이번 주 핵심'` 으로 대체하려 했음. 그런데 ::before 가 flex item 으로 들어가면서 white-space/flex-shrink 가 제대로 잡히지 않아 좁은 공간에서 한 글자씩 세로로 무너짐. font-size:0 + flex + ::before 조합이 모바일 폭에서 깨짐.
- **수정**:
  - CSS 에서 `font-size:0` / `::before content` 트릭 전부 제거
  - JS 로 `.panel-hero .panel-head` innerHTML 을 깔끔히 재작성: `<span class="s36-title">이번 주 핵심</span><span class="label" id="hl-count">…</span>`
  - `flex-shrink:0; white-space:nowrap` 로 절대 줄바꿈 안 되게 잠금
  - `data-s36` 가드로 중복 적용 방지, renderHome 후에도 재적용

### 2) Home 카드 리듬
- 상황판 셀 padding `11px 13px 12px`, min-height 74px, sb-v 17px, sb-sub 11px 로 정돈
- 칩 줄(`focus-chips/sb-chips/sit-chips`) gap 5/6, padding 3×8, font 10px
- `#page-home gap 10px`, situation/hero/kpi 사이 margin 0 통일 → vertical rhythm 자연스럽게

### 3) 고양이 마스코트
- Home `.panel-hero` 안에서만 유지
- `scale(0.55)`, opacity 0.55, top 6px / right 10px 로 더 작고 더 흐리게
- `lucky-pulse` 펄스 끄고 tail 만 5s 로 느리게
- `.cat-coin-plus` 숨김, glow 거의 제거 → 보조 마스코트 톤

### 4) AI 스테이션 카드 압축
- `#ws-grid.v28` padding-left 44 → 34
- 카드 padding 14→11, columns 100/1fr/120 → 88/1fr/108
- icon 100×74 → 88×62
- info gap 6→5, role 13→12, status 11→10, prov 10→9
- `.ws28-b .ln`: font 11→10.5, line-height 1.5→1.45, **white-space:nowrap + ellipsis** (담당/최근/다음 줄 한 줄로 깔끔하게)
- `.k` 라벨 9→8.5, min-width 26→22

### 5) 좌측 0105 트랙 정리
- 세로 rail left 22→14, opacity 0.9→0.45, dash 3/6 → 2/5 로 더 얇고 흐리게
- `.ws28-step` 좌측 22px 안쪽으로, font 9→8, opacity 0.55, 점 5×5 로 축소
- working 일 때만 살짝 살아남게 (`opacity:0.85`, 보조 ring)

### 6) AI 우측 today/runs/chart 정렬
- `.ws28-c` align-items flex-end + min-height 54 + 보조선 일관
- runs 24→21, letter-spacing -0.5
- lbl 9→8.5, letter-spacing 0.6
- strip height 14→12, 막대 lo/md/hi 4/8/13 → 3/7/11
- 카드마다 우측 블록 baseline grid 일정

### 7) Home KPI 4카드
- `display:grid; columns 1fr auto; rows auto auto`
- k-label 위, k-sub 아래, k-val 우측 세로 중앙 정렬 (baseline grid)
- min-height 46, font 16→18 (k-val), label 9px uppercase

### 8) 공통 타이포
- `font-feature-settings:"tnum","ss01"` Home/AI 둘 다 적용
- 카드 내부 align-items center 통일

### 수정 파일
- `static/dashboard.html` (S36 style block + S36 highlight head JS, S35 블록 위에 prepend)

### 커밋
- `dashboard S36: Home + AI detail polish (highlight header fix, card rhythm, cat, station compression, track/today align)`

### Push
- `claude/extract-prediction-time-n82UK` ✓
- `claude/premium-control-room-ui-LJFba` ✓

## S36b — 추가 보정 (Home only)

### 1) 섹션 순서 잠금
- `order:1` 상황판 / `order:2` 하이라이트 / `order:3` KPI / `order:4` 시스템 상태 (hero/hero-compact)
- 모두 `!important` 로 잠금. 다른 탭은 안 건드림.

### 2) 시스템 상태 카드 비대 원인
- `.hero` 가 flex 컨테이너 안에서 `flex:1 1 auto` 로 늘어나 page 의 빈 공간을 다 빨아먹음
- 내부에 hero-poster/hero-big/hero-grid 같은 잔재 블록이 큰 padding 가지고 있었음
- 수정: `flex:0 0 auto`, `min-height:0`, `padding 8×12`, `border:1px dashed`, hero-poster/hero-big/hero-grid `display:none`. 한 줄 보조 strip 으로 축소.

### 3) "이번" 세로 깨짐 — 보강
- S36 1차 수정만으로 부족했던 케이스 (특정 폭에서 여전히 깨짐)
- 추가: `writing-mode:horizontal-tb`, `word-break:keep-all`, `text-orientation:mixed`, `white-space:nowrap`, `overflow:visible` 를 panel-head 와 .s36-title 양쪽 모두에 강제
- `.s36-title { display:inline-block; flex:0 0 auto; max-width:none }` 로 절대 줄바꿈/축소 안 되게 잠금
- panel-head 자체에 `width:100%; min-width:0; box-sizing:border-box` 명시

### 4) 고양이 추가 정리
- scale 0.55 → 0.42, opacity 0.55 → 0.42
- right 10→8, top 6→4
- 모든 자식 애니메이션 정지 (`* { animation:none }`)
- coin-rush filter 도 제거 → 떠 있는 장식 느낌 완전 제거

### 수정 파일
- `static/dashboard.html` (S36b 블록을 S36 위에 prepend)

### 완료 기준
- ✅ "이번" 세로 깨짐 사라짐 (font-size:0 + ::before flex 트릭 제거, JS 로 직접 재작성)
- ✅ Home 카드 리듬 정돈
- ✅ 고양이 보조 마스코트화
- ✅ AI 카드 더 짧고 한 줄로 정렬
- ✅ 좌측 트랙/우측 today 마감
