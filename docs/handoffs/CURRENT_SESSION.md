# Current Session — 2026-04-07 (Session 37)

## S37 — Cat free-roaming pet + AI card layout rebuild

`static/dashboard.html` 만. 새 구조/기능 없음.

### 1) 고양이가 왜 스티커처럼 보였나
- S36/S36b 까지 고양이는 `#page-home .panel-hero` 안에 `position:absolute; top/right` 으로 박혀 있었음
- 카드 모서리에 고정되어 있고, transform scale 0.42 로 작아지고 opacity 0.42 로 흐려져서 → "PNG 스티커" 느낌
- 카드 안에서 한 자리에 묶여 있어서 살아있는 존재감이 0

### 2) 고양이 재설계
- DOM 이동: JS 로 `#cat` 을 `#page-hero` 안에서 꺼내 `#page-home` 직속 자식으로 이동
- `#page-home` 에 `position:relative` 부여 → 페이지 전체 좌표계에서 자유 이동
- 56×56, opacity 0.78, glow/필터 전부 제거
- **방랑 (wander)**: 6개 perch 좌표 (top-right, top-left, bottom-right, bottom-left, mid-right, mid-left) 사이를 22~38초 간격 랜덤으로 이동
- 이동은 `transition:left/top 2.4s ease-in-out` 로 천천히 걸어가는 듯한 보간
- 좌측 perch 일 때는 `scaleX(-1)` 로 자연스럽게 방향 반전
- 애니메이션은 꼬리(5.5s) + 눈깜빡임(6s) 만 유지, 코인/펄스/얼럿 전부 끔
- 데이터/버튼 보호: perch 좌표는 카드 외곽 margin 영역에만 배치 (콘텐츠 위로 올라가지 않음)
- Home 활성일 때만 보이게 MutationObserver 로 감시
- resize/orientation 대응: 200ms debounce 후 perch 재계산

### 3) AI 카드 텍스트 폭이 좁았던 원인
- 기존: `.ws28` 가 3-column grid `88px 1fr 108px` (S36 압축 후)
- 모바일 폭 ~360px 에서: 88(아이콘) + 108(우측 today) + gaps 24 + 좌패딩 30 = 250px 점유 → 가운데 텍스트 영역 ~110px 만 남음
- "5기준 체크 완료 · perplexity" 같은 문장이 강제로 줄바꿈, "→ DraftWriter 에 컨텍스트 공급" 도 깨짐

### 4) AI 카드 레이아웃 재구축 (CSS-only, DOM 그대로)
```
grid-template-columns: 58px 1fr;
grid-template-areas:
  "icon info"
  "icon meta";
```
- `.ws28-icon` → icon 영역, 58×54 로 축소 (오버사이즈 포스터 느낌 제거)
- `.ws28-info` → info 영역, 텍스트가 카드 폭의 ~75% (1fr - 58 - 12) 사용
- `.ws28-c` → meta 영역, info 바로 아래로 내려가 가로 strip (runs · TODAY · chart) 로 재구성. `border-left` 제거, `border-top:1px dashed` 로 구분.
- icon 이 두 행 모두 차지 (`grid-area:icon` rowspan)

### 5) AI 카드 타이포 재정리
- `.ws28-role` 13px 600
- `.ws28-status` 11px (dot 6px)
- `.ws28-prov` margin-left:auto 로 우측 끝, 10px pill
- `.ws28-b .ln` 11.5px / line-height 1.5 / `word-break:keep-all` (한국어 단어 깨짐 금지) / nowrap 해제
- `.k` 라벨 9px uppercase, 고정폭 26px → 본문이 항상 같은 위치에서 시작
- `.ws28-b .ln.next` padding-left:33px (라벨 폭 + gap) 로 본문 정렬에 맞춤
- runs 18px / lbl 8.5px / strip max-width 140px 우측 정렬 → 한 줄 footer 깔끔

### 6) 좌측 0105 트랙
- rail left 13px, opacity 0.35
- step 마커 left -22, font 8, opacity 0.5 (working 일 때만 0.85)
- top:18px 로 카드 첫 줄 baseline 근처

### 수정 파일
- `static/dashboard.html` (S37 script + style 블록을 S36b 위에 prepend, style/script 태그 균형 맞춤)

### 커밋
- `dashboard S37: cat as free-roaming Home pet + AI card 2-row grid rebuild`

### Push
- `claude/extract-prediction-time-n82UK` ✓
- `claude/premium-control-room-ui-LJFba` ✓

---

# Previous Session — 2026-04-07 (Session 36)

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
