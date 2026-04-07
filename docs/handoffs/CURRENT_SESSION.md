# Current Session — 2026-04-07 (Session 21)

## What Was Done This Session

### Pixel HUD Dashboard — S21 (Human-level polish + Home focus)

S18(rebuild) → S19(Korean/mobile) → S20(polish) → **S21(human-level + Home focus)**.
백엔드/스키마/승인 워크플로 변경 없음. `static/dashboard.html` 단일 파일만.

S21은 두 단계로 진행되었음:
(a) 전반적 휴먼 레벨 폴리시 — S20 위에 S21 스텝 1~5 적용 (토큰·글로우 미세조정, 신규 컴포넌트 CSS, HTML 구조 정리, 홈 spark + attention-band, AI 워커 프레즌스)
(b) **Home 집중 리파인 (이번 커밋 핵심)** — "사람이 마감한 운영실 메인 화면" 느낌

### Home 집중 변경

1. **Hero 위계 강화**
   - `hero-state .label` 34px/700/+1px → **38px/800/-0.5px**, text-shadow 0.25→0.30
   - `.sub` 색을 txt → txt2 로 낮춰 주상태와 분리

2. **hero-summary 4칩 강조 (숫자+라벨 한 단위)**
   - flex → **4-column grid**(모바일 2-column), 칩 형태 (`surface-2` 배경, 좌측 2px accent 라인)
   - 라벨 11px/600/txt3, **숫자 20px/800/tnum/-0.5px**
   - 칩별 좌측 보더 색: 초안=news / 승인대기=ok / 프리미엄=premium / B2B=b2b

3. **Weekly 하이라이트 홈 중심 승격 (`.panel-hero`)**
   - 새 클래스 `.panel-hero` 추가 — 테두리 accent 알파 0.28, 내부 accent 인셋 글로우
   - 헤더 `◆ 이번 주 하이라이트`, 카운트 라벨 13/700/txt
   - `.hl-item` padding 11→12, font 13→14, 좌측 보더 3→4px, hook 600

4. **Lucky cat `warning` 상태 연결**
   - `applyCatState()` 클리어 목록에 `warning` 추가
   - 분기: db_ok=false → alert / is_idle → idle / telegram|X 미설정 → **warning** / 기본 → lucky-pulse (+ coin-rush / lean-weekly)
   - warning CSS(6~7s 느린 paw/tail, 앰버 글로우)는 S21 (a) 단계에서 이미 추가되어 있음

### 변경되지 않은 것 (의도)

- 백엔드 / 스키마 / 테스트 / 승인 워크플로 / 자동 발행
- Intake 4 lane / Ops 6 카드 구조
- AI 5 노드 워커 프레즌스 (S21 a 단계에서 적용 완료)
- Strip / KPI 그리드 자체 구조
- 고양이 SVG 자체, 다른 상태(alert/idle/coin-rush/lean-weekly/healthy)

## Files Changed

| File | Change |
|------|--------|
| `static/dashboard.html` | S21 누적 + Home 집중 (hero 위계, hero-summary 칩, panel-hero, cat warning 분기) |
| `docs/handoffs/CURRENT_SESSION.md` | S21 entry |
| `docs/handoffs/LATEST_STATUS.md` | S21 entry |

## Branches

- `claude/extract-prediction-time-n82UK`
- `claude/premium-control-room-ui-LJFba`

양 브랜치 동기화.

## Manual Verification

1. iPhone 375px — hero 상태가 38px 로 강조, 4-칩이 2x2 로 떨어짐
2. hero-summary 각 칩의 라벨/숫자가 한 단위로 읽힘
3. 이번 주 하이라이트 패널이 accent 테두리로 홈 중심 요소처럼 보임
4. 텔레그램/X 미설정일 때 고양이가 `warning` 으로 긴장감 있는 모션
