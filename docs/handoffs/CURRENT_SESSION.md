# Current Session — 2026-04-07 (Session 52)

## S52 — AI 카드 아이콘 왼쪽 gutter 미세 정리 (1줄)

**원인**: `#ws-grid.v28 { padding-left:26px !important }` @ L5837. step 번호 rail용 여분이 과했음.
**수정**: 26px → 20px. step(`.ws28-step { left:-18px }`)은 그대로. 카드가 viewport 20px에서 시작, step은 2px 지점에 위치.
**영향**: 아이콘/텍스트/차트/탭 로직 모두 무영향.

---

# Previous — Session 51 — Forensic

## S51 — AI 카드 아이콘/텍스트 충돌 수리 (역할명 첫 글자 잘림)

`static/dashboard.html` 만. AI 탭 한정. 삭제-온리.

### 스크린샷 증거
"뷰어", "서처", "트체커", "렌드 헌터" — 역할명 첫 글자(리/리/팩/트)가 아이콘 박스에 덮여 잘림.

### Root Cause
S28 L4804 `#ws-grid.v28 .ws28-icon { width:80px !important; height:56px !important }` 가 여전히 살아있었음.
- specificity `#id + 2 class` > S37의 `.ws28-icon{width:52px !important}` (1 class)
- S28이 이겨서 아이콘 실제 width = 80px
- 그러나 S37의 grid-template-columns 는 `52px 1fr`
- 80px 아이콘 박스가 52px 컬럼을 **28px 오버플로우**해서 텍스트 컬럼 첫 글자를 덮어씀

추가: @media(max-width:760px) L4888 `#ws-grid.v28 .ws28-icon{width:70px}` 도 같은 방식으로 iPhone에서 70→52 오버플로우.

### 실제 수정 (삭제 2줄)
1. L4804 `#ws-grid.v28 .ws28-icon{width:80px;height:56px}` → 삭제
2. L4888 `#ws-grid.v28 .ws28-icon{width:70px;height:50px}` (미디어쿼리) → 삭제

결과: S37 canonical `.ws28-icon{width:52px;height:50px}` 가 유일 규칙. 아이콘이 52px 컬럼 안에 정상 수납되고 텍스트 시작점 침범 없음. `.ws28-info { min-width:0 }`(S37 L5557)과 `grid-template-columns:52px 1fr` 로 텍스트 시작선이 카드마다 고정.

### Do Not Touch
S37 canonical block, S50 tab fix, S50 좌측 밀도(26/52/10), S50 micro chart, 다른 탭.

---

# Previous — Session 50 — Forensic

## S50 — Tab 전환 + micro chart + 좌측 밀도 (포렌식)

`static/dashboard.html` 만. 새 구조 추가 없음.

### Root Cause (tab 전환)
L3888 / L4996 / L5005 / L5026 / L5032 에 `#page-home{display:flex}` `#page-ai{display:flex}` `#page-intake{display:flex}` `#page-ops{display:flex}` 가 **`.active` 한정 없이** 걸려 있었음. specificity `#id`(1 ID) > `.page.active`(2 class). → `.page{display:none}`/`.active{display:block}`를 모두 이김. **네 페이지가 상시 display:flex 로 stack 노출**. 탭 click은 `.active` class만 바꾸고 시각적으로 아무 효과 없음.

Tab JS handler는 이미 S35(5092~5127) 단 하나로 cloneNode 체인 끝에 정리돼 있어 문제 없음. 문제는 CSS selector만.

### Root Cause (micro chart)
S48 `border-bottom:1px solid` axis가 `.ws28-c`의 `border-top:1px dashed`와 수직 근접해 이중선. `min-width:104px`가 우측 rail에 붕 뜬 느낌.

### Root Cause (좌측 여백)
`#ws-grid.v28{padding-left:34px}` + `icon 58px` + `column-gap 12px` = 카드 본문까지 104px 좌측 dead zone. Step rail은 24px면 충분.

### 실제 수정 (삭제/치환만)
1. **Tab CSS (5줄)**: `#page-home`/`#page-ai`/`#page-intake`/`#page-ops` 의 `{display:flex...}` 규칙 5곳 모두 `.active` 한정사 추가. L3888, 4996, 5005, 5026, 5032.
2. **Micro chart** (L5585~5592): `border-bottom` 제거, `padding-bottom:1px` 제거, `margin:0 0 1px auto` → `0 0 0 auto`, `height:16px`→`14px`, `min-width:104`→`72`, `max-width:140`→`110`.
3. **좌측 밀도**:
   - `#ws-grid.v28{padding-left:34px}` → `26px` (L5824)
   - `.ws28 grid-template-columns:58px 1fr` → `52px 1fr`
   - `.ws28 column-gap:12px` → `10px`
   - `.ws28 padding:12px 10px 12px 0` → `12px 8px 12px 0`
   - `.ws28-icon width:58;height:54` → `52; 50`
   - `.ws28-step left:-22px` → `-18px`

### Do Not Touch
S35 tab JS handler, S37 grid-template-areas, S47 `#page-ai.page` padding, 고양이, 헤더, 백엔드, 승인 로직, 다른 탭 콘텐츠.

---

# Previous — Session 49 — Forensic

## S49 — AI 카드 우측 모듈, stale override 제거 (삭제-온리)

`static/dashboard.html` 만. AI 탭 한정. 새 CSS 추가 없음. 원인 라인 삭제만.

### 포렌식 결과
AI 카드 레이아웃 CSS가 4겹 누적:
1. 원본 (3398, 3561)
2. S28 compact (4796~4826)
3. **S31 — 오염원 (5833~5900, 5909)**: 3-col 그리드 `88px 1fr 108px` + `.ws28-c`를 우측 rail로 정의 (border-left dashed, min-height 54, align-items flex-end)
4. S37/S46/S48 (5550~5603): 2-col 그리드 `58px 1fr` + `grid-template-areas:"icon info"/"icon meta"` — `.ws28-c`를 하단 meta 행으로 재배치

### Root Cause
S31 블록이 S37 재설계를 부분적으로 덮고 있었음:
- `grid-template-columns:88px 1fr 108px` 가 source order로 S37의 2-col을 이김
- `grid-template-areas` 는 그대로라 **108px 3번째 컬럼이 dead column으로 버려짐** → 우측 모듈이 "붕 뜬" 체감의 정체
- `.ws28-c` 를 좌측 세로 rail 스타일(border-left dashed)로 재정의 → S37의 하단 meta 행과 충돌
- `#page-ai .ws28-c{align-items:center}` 가 specificity로 S48 baseline 정렬을 **말없이 무효화**
- `#ws-grid.v28 .ws28-c{padding-left:6px;gap:2px}` (S28) 가 specificity로 S37을 이기고 있었음

### 실제 삭제
1. `#ws-grid.v28 .ws28-c {...}` + `.runs/.lbl/.strip` 서브룰 @ 4820–4826 → 전체 삭제
2. `#ws-grid.v28 .ws28 { grid-template-columns:88px 1fr 108px; align-items:center }` + `.ws28-icon{88×62}` @ 5835–5840 → 삭제
3. `.ws28-c { border-left:1px dashed; min-height:54 ... }` + `.runs/.lbl/.strip` @ 5879–5900 → 블록 전체 삭제
4. `#page-ai .ws28-a, .ws28-b, .ws28-c { align-items:center }` @ 5909 → 삭제

### Do Not Touch (건드리지 않음)
- S37 canonical block @ 5550–5603 (2-col + grid-areas)
- S48 micro chart @ 5585–5596
- S47 `#page-ai.page` padding-bottom @ 5184
- `@media (max-width:760px)` .ws28-c 재정의 @ 4874–4887 (S37과 호환)
- 다른 탭의 어떤 selector

### 왜 최소 수정인가
- 새 CSS 한 줄도 추가하지 않음. 순수 삭제.
- S31 유령 블록만 걷어내면 S37/S48이 자동 활성화.
- 다른 layer 무영향.

---

# Previous — Session 48

## S48 — AI 탭 마감 폴리시 (micro chart + 우측 정렬 + 하단 여백)

`static/dashboard.html` 만. AI 탭 한정. 버그 수정 아님, 마감 디테일.

### 변경
1. **Micro chart 폴리시** (`.ws28-c .strip`)
   - height 18 → 16, bar 4px → 3.5px, gap 2.5 → 3px
   - 막대 높이 단계 5/11/17 → 4/9/14 (부드러운 계단)
   - `border-bottom:1px solid var(--line)` baseline 축 추가
   - 막대 top radius `1px 1px 0 0`, opacity 0.55/0.75/0.95 단계
   - min-width 96 → 104, `align-self:flex-end` 행 바닥 앵커
   - → 장식 spark bar가 아니라 실제 activity 그래프 느낌

2. **우측 정보 모듈 기준선** (`.ws28-c`)
   - `align-items:center` → `align-items:baseline`
   - gap 10 → 8
   - runs / lbl `align-self:baseline`, 불필요한 padding-top 제거
   - → provider pill / runs / label / chart 같은 baseline 공유, 카드마다 흔들림 제거

3. **마지막 카드 하단 여백**
   - `#page-ai.page` padding-bottom 16px → 10px
   - 과공백 없이 자연스러운 마감

### 결과
- Micro chart가 작지만 "실제 activity" 축을 가진 그래프처럼 보임
- 우측 정보 모듈이 카드 간 안정적으로 정렬됨
- 마지막 카드 아래 10px breathing room, 화면 끝에 붙지도 뜨지도 않음
- AI 탭 = 마감된 제품 느낌

---

# Previous — Session 47

## S47 — AI 탭 레이아웃 해킹 제거, 자연 흐름 복귀

`static/dashboard.html` 만. AI 탭 한정. 디자인/색/타이포 무변경.

### 문제 진단
S39/S41/S46의 hack들이 void의 원인이었다:
- JS가 `#page-ai` 높이를 `.hud-main.clientHeight`로 강제 → 뷰포트 높이로 늘림
- `#ws-grid.v28 justify-content:space-between` → 카드 사이·하단 공백 강제 벌림
- 마지막 카드 inline margin/border hack

### 변경
- S41 forceAiBottom IIFE 전체 제거 (주석만 남김)
- S40 specificity CSS 블록을 S47로 교체:
  - `#page-ai.page`: `padding-bottom:16px`, `height:auto`, `min-height:0`, `display:block`
  - `#ws-grid.v28`: `justify-content:flex-start`, `height:auto`, `min-height:0`, `padding-bottom:0`
- `justify-content:space-between` 금지 규정 반영
- 마지막 카드 inline hack 제거
- S46 micro chart CSS (height 18, 4px bars, lo/md/hi 5/11/17, min-width 96px) 보존

### 결과
- AI 탭 = 자연 블록 흐름. 카드 위→아래로 쌓임
- 하단 공백은 16px 한 겹만
- 뷰포트 강제 stretch 제거 → void 소멸

---

# Previous — Session 46

## S40~S46 — AI bottom void & micro chart (iterative chase)

`static/dashboard.html` 만. AI 탭 한정.

### S40~S45 결론
- S40: specificity 끌어올림 (`html body .hud-main #page-ai.page`) — S35 의 `#page-ai{padding-bottom:0!important}` 가 source 뒤에 있어 같은 specificity 면 나중이 이김. 끌어올려 우회.
- S41: inline JS `setProperty('padding-bottom','...','important')` 로 cascade 무시. 140px 줬다가 과해서
- S42: 20px 로 축소
- S43: 카드 키워서 채우려다 사이즈 변화 거부됨
- S44: 카드 사이즈 복구 + padding 0 + hud-main padding 0 + 마지막 카드 margin 0
- S45: 카드 합 < 페이지 높이라서 padding 0 만으론 부족 → flex space-between 도입

### S46 — micro chart 정상화 + 정확한 높이 강제
**1) Micro chart 찌그러진 원인**
S37 의 `.ws28-c .strip` 가 `height:12px`, bar `width:3px`, lo/md/hi `3/7/11px`. 12px 높이에 3px 폭 막대 8개라 시각적으로 눌린 장식처럼 보임. 또 `flex:1 1 auto` + `max-width:140px` 만 있고 `min-width` 가 없어 좁은 폭에선 squeeze.

**Fix**:
- height 12 → 18px
- bar width 3 → 4px, gap 2 → 2.5px
- lo/md/hi 3/7/11 → 5/11/17px
- `min-width: 96px` (절대 squeeze 안 됨)
- `flex: 0 0 auto` + `margin-left: auto` 로 우측 고정
- runs 18 → 19px, lbl 8.5 → 9px, padding 6/0 → 8/4 로 baseline 정돈

**2) AI 우측 정보 블록 기준선**
runs/lbl/strip 모두 `align-self:center`, `.ws28-c { align-items:center }` → 카드마다 우측 블록 baseline 일정.

**3) 하단 공백 원인**
S45 의 `min-height:100%` 가 `#page-ai` 부모(`.hud-main`)의 computed height 에 의존. iOS Safari 의 dynamic viewport 에서 부모 height 가 계산 시점에 따라 다르게 잡혀 #page-ai 가 실제 viewport 보다 작게 잡히고, flex space-between 의 분배 영역이 줄어 → 마지막 카드 아래 빈 공간 발생.

**Fix (정확한 픽셀 강제)**:
- JS 가 `.hud-main.clientHeight` 를 읽어 실제 scroll viewport 픽셀 높이 측정
- `#page-ai { height: <hudH-14> px; min-height: <hudH-14>px }` 인라인 강제
- `.hud-main padding-top: 14px` (헤더 호흡 유지) / padding-bottom: 0
- `#ws-grid { flex: 1 1 auto; min-height: 0; padding-bottom: 0 }`
- `space-between` 분배 → 5 카드가 정확한 픽셀 높이 안에서 균등 배치 → 마지막 카드 = 정확히 viewport 바닥

### 수정 파일
- `static/dashboard.html`

### 커밋 (S40~S46)
- `9c8e820` S40 specificity bump
- `b6c1282` S41 inline JS bulletproof
- `7dceca6` S42 trim 140→20
- `2a26d4e` S43 enlarge cards (reverted)
- `d28ca16` S44 size revert + padding 0
- `82c1ab2` S45 flex space-between
- `6fd8128` S46 micro chart restored + exact pixel height

### Push
- `claude/extract-prediction-time-n82UK` ✓
- `claude/premium-control-room-ui-LJFba` ✓

---

# Previous Session — 2026-04-07 (Session 39)

## S39 — Cat continuous walk + AI bottom cut full fix

### 1) 고양이 순간이동 실제 원인
S38 은 6개 perch CSS 클래스를 토글하는 방식이었음. 각 클래스가 `top/right` 또는 `bottom/left` 를 사용. 클래스가 바뀔 때 예: `top:8;right:10;left:auto;bottom:auto` → `top:auto;right:auto;left:10;bottom:14`. **CSS transition 은 `auto` 값을 보간하지 못함** → top/right/left/bottom 사이 전환이 즉시 일어남 → 순간이동처럼 보임. transition 은 선언했지만 실제로는 jump.

### 2) 이동 방식 재설계 (transform interpolation)
- **단일 좌표계**: cat 을 `top:0; left:0` 에 고정. 이동은 **`transform: translate(var(--tx), var(--ty)) scaleX(var(--flip))`** 로만 처리.
- transform 은 CSS transition 이 완벽히 보간 → 진짜 연속 이동.
- waypoint 를 좌표(px)로 계산: `bounds()` 가 home 의 안전 roaming 영역(외곽 margin 8 + bottom 60px 보호) 을 산출.
- waypoints: 6개 가장자리 점 (TR → MR → BR → BL → ML → TL) — 카드 본문 위를 절대 가로지르지 않음 (외곽선만 따라 걷는 느낌).
- 이동 시간: 거리 ÷ 60 (px/s) 로 4.5~9초. 매우 느린 걸음.
- 정지(rest): 3.5~7.5초 랜덤. "걸었다 → 쉬었다 → 또 걷는" 펫 리듬.
- 방향 반전: `--flip` 는 walk 시작 직전 즉시 적용 (rAF 분리) → 걷는 방향과 face 방향이 자연스럽게 일치.
- 첫 spawn: TR 좌표에 즉시 보임. 4.5초 후 첫 walk 시작.
- resize: 300ms debounce 후 path 재계산만, 현재 위치 jump 안 함.

### 3) 표시/숨김 정리
- opacity/display 토글 완전 제거. cat 은 항상 `opacity:0.92`, `display:block`.
- 가시 정책은 부모 `#page-home.active` cascade 에 위임 (S35 truth rule). MutationObserver 없음, 깜빡임 없음.
- `cat.dataset.s37/s38/s39 = '1'` 로 이전 IIFE 들 early return 보장.

### 4) AI 하단 잘림 원인 (S38 부족분)
S38 에서 `.hud-main { bottom: calc(--tab-h + safe-area) }` 만 적용. 그런데 iPhone Safari 의 dynamic toolbar (스크롤 시 나타나는 하단 바) 가 추가로 viewport 를 침범하고, `#page-ai padding-bottom:24px` 로는 마지막 카드의 chart/숫자가 여전히 가려짐.

### 5) 하단 여백 조정 (충분한 슬랙)
- `.hud-main { bottom: calc(var(--tab-h) + env(safe-area-inset-bottom, 0px)) }` 유지
- `#page-ai { padding-bottom: calc(72px + env(safe-area-inset-bottom, 0px)) !important }` — AI 한정 강한 슬랙. iPhone Safari dynamic toolbar 까지 흡수.
- `#page-ai #ws-grid.v28 { padding-bottom:8px }` 추가
- `#page-ai .ws28:last-child { margin-bottom:16px; border-top:1px dashed; border-bottom:none }`
- 다른 탭은 영향 없음 (AI scope only).

### 수정 파일
- `static/dashboard.html`

### 커밋
- `dashboard S39: cat continuous walk via transform interpolation + AI hard bottom slack`

### Push
- `claude/extract-prediction-time-n82UK` ✓
- `claude/premium-control-room-ui-LJFba` ✓

---

# Previous Session — 2026-04-07 (Session 38)

## S38 — Cat visibility fix + AI bottom cut fix

`static/dashboard.html` 만.

### 1) Home 고양이가 안 보였던 실제 원인
S37 의 setupCat 은 `home.clientWidth/clientHeight` 를 읽어 perch 좌표를 계산했음. 그런데 S37 IIFE 가 실행되는 시점에 `#page-home` 은 아직 `.active` 클래스가 없는 상태 → S35 의 `.page:not(.active){display:none}` 규칙으로 `display:none` → `clientWidth/Height = 0` → perch 가 모두 `left: w-64 = -64px`, `top: 6px` 같은 음수/화면 밖 좌표로 계산됨. 결과: 인라인 `style.left = -64px` 가 박힌 채 cat 이 화면 왼쪽 밖으로 사라짐. 이후 S35 가 home 을 active 로 만들고 MutationObserver 가 display 를 풀어줘도, 잘못된 인라인 left/top 은 그대로 남아 cat 은 영영 안 보임.

### 2) Home 고양이 복구
- **right/bottom anchor 방식**: `clientWidth` 의존 제거. 6개 perch 를 CSS class (`s38-tr/tl/br/bl/mr/ml`) 로 정의, 각 class 가 `top/right` 또는 `bottom/left` 만 사용. 어떤 layout 상태에서도 화면 안에 자동 배치됨.
- 초기 perch: `s38-tr` (top-right) — 항상 즉시 보임. 첫 렌더 invisible 금지 조건 충족.
- JS: S37 의 인라인 `left/top` 다 제거 후 `cat.dataset.s37 = '1'` 로 표시해 S37 IIFE 가 early return 되도록 막음 (중복 실행 방지).
- 60×60, opacity 0.92, z-index 9, glow 없음.
- 9초 후 wander 시작, 24~38초 간격으로 다음 perch 로 천천히 이동 (`transition: top/right/left/bottom 2.2s ease-in-out`).
- 좌측 perch 도착 시 `transform: scaleX(-1)` 로 방향 자동 반전.
- 표시 가시 정책: `#page-home` 자체가 `display:none` 일 때 자식인 cat 도 자동 숨김 (S35 truth rule 에 위임). MutationObserver 같은 가짜 게이트 제거.
- Home 진입 = 무조건 cat 보임. 다른 탭에서는 부모가 hidden 이라 자동 숨김.

### 3) AI 탭 하단 잘림 원인
`.hud-main` 은 `position:fixed; bottom:var(--tab-h)`. 하지만 `.hud-tabs` 는 `padding-bottom:env(safe-area-inset-bottom)` 로 iPhone 홈 인디케이터 영역만큼 더 아래까지 차지함. 즉 실제 가시 탭바 높이 = `--tab-h + safe-area-inset-bottom`. 그런데 hud-main 의 bottom 은 `--tab-h` 만 빼고 끝 → 스크롤 영역 마지막 ~20-34px 가 탭바 뒤에 깔림. 마지막 AI 카드의 chart/숫자가 가려짐.

### 4) 하단 여백 수정
- `.hud-main { bottom: calc(var(--tab-h) + env(safe-area-inset-bottom, 0px)) !important; padding-bottom:16px !important }` — 스크롤 컨테이너 자체를 safe-area 만큼 더 위로 밀어 올림. 전역 보정.
- `#page-ai { padding-bottom:24px !important }` — AI 탭 한정 추가 슬랙. 마지막 카드와 탭바 사이 호흡.
- `#page-ai #ws-grid.v28 .ws28:last-child { margin-bottom:12px; border-bottom:none }` — 마지막 카드 dashed 보더 제거 + 추가 margin.
- 과한 빈 공간 X / 잘림 X.

### 수정 파일
- `static/dashboard.html` (S38 style + script 블록을 S37 위에 prepend, 태그 균형 OK)

### 커밋
- `dashboard S38: cat visibility fix (right/bottom anchored perches) + AI bottom cut fix (safe-area)`

### Push
- `claude/extract-prediction-time-n82UK` ✓
- `claude/premium-control-room-ui-LJFba` ✓

---

# Previous Session — 2026-04-07 (Session 37)

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
