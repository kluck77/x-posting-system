# Latest Status

## LAST COMPLETED PHASE: Dashboard S39 — Cat continuous walk + AI bottom cut full fix

`static/dashboard.html` only.

**Cat teleport root cause**: S38 toggled CSS classes that switched between `top/right` and `bottom/left` anchors. CSS transitions cannot interpolate between explicit values and `auto` → property changes were instant despite transition declaration. Looked like teleport.

**Fix**: single coordinate system. Cat anchored at `top:0;left:0` and moved via `transform: translate(--tx,--ty) scaleX(--flip)` only. transform interpolates smoothly. JS walks 6 perimeter waypoints (TR→MR→BR→BL→ML→TL) at ~60px/s = 4.5–9s slow walks separated by 3.5–7.5s rests. Direction flip applied via rAF before walk starts. No opacity/display toggles. Visibility delegated to `#page-home.active` cascade.

**AI bottom slack**: bumped `#page-ai { padding-bottom: calc(72px + env(safe-area-inset-bottom)) }` to absorb iPhone Safari dynamic toolbar; last `.ws28` margin-bottom 16, border-top dashed.

## PREVIOUS PHASE: Dashboard S38 — Cat visibility fix + AI bottom cut fix

`static/dashboard.html` only.

**Cat invisible root cause**: S37 setupCat read `home.clientWidth/Height` to compute perches, but at IIFE boot `#page-home` was still `display:none` (S35 hadn't fired yet) → clientWidth=0 → cat got inline `left:-64px` and stayed off-screen forever even after S35 activated home.

**Fix**: switched to right/bottom CSS anchors via 6 perch classes (`s38-tr/tl/br/bl/mr/ml`), no `clientWidth` dependency. Initial perch `s38-tr` always renders inside viewport. JS sets `cat.dataset.s37='1'` to early-return the legacy S37 IIFE. Visibility delegated to parent `#page-home` display state (S35 truth rule) — no MutationObserver gate.

**AI bottom cut root cause**: `.hud-main` used `bottom:var(--tab-h)` but `.hud-tabs` padded `env(safe-area-inset-bottom)` → real tab height exceeded scroll-area bottom by ~20-34px on iPhone, hiding last AI card behind the home indicator.

**Fix**: `.hud-main { bottom: calc(var(--tab-h) + env(safe-area-inset-bottom, 0px)) }` + `#page-ai { padding-bottom:24px }` + last `.ws28` margin-bottom 12px / no border-bottom.

## PREVIOUS PHASE: Dashboard S37 — Cat free-roaming pet + AI card layout rebuild

`static/dashboard.html` only.

**Cat**: detached from `.panel-hero` (was a corner sticker), moved to `#page-home` direct child, free-roaming between 6 perch coordinates with 22-38s slow walk transitions, scaleX flip on left perches, blink+tail only, glow off, MutationObserver hides on non-home tabs. "회사에서 키우는 작은 펫" feel.

**AI cards**: 3-col grid `88/1fr/108` was choking text to ~110px on mobile. Rebuilt as 2-col + 2-row grid via `grid-template-areas: "icon info" "icon meta"` — info now gets ~75% of card width, meta (runs · TODAY · chart) becomes a horizontal footer strip below info. Icon shrunk to 58×54. Text uses `word-break:keep-all`, fixed-width `.k` labels (26px) so 담당/최근/다음 baseline-align. provider pill pinned right via `margin-left:auto`. Korean wrapping fixed.

## PREVIOUS PHASE: Dashboard S36 + S36b — Home/AI Detail Polish & Final Hardening

`static/dashboard.html` only. No backend, no new structure.

**S36 (polish)**: Home highlight header bug (font-size:0 + ::before flex trick) replaced with JS-injected clean `.s36-title` span. Situation/KPI/cat rhythm tightened. AI ws28 cards compressed (88×62 icon, 11px padding, nowrap+ellipsis lines). Left rail/0105 markers faded (opacity 0.45/0.55). Right today/runs/strip baseline grid normalized.

**S36b (hardening)**: Home section order locked via `order:1..4` (situation → highlight → KPI → system status). System status `.hero` was eating page height via `flex:1 1 auto` + leftover hero-poster/big/grid blocks → forced `flex:0 0 auto`, killed leftover blocks, padding 8×12. "이번" title fix reinforced with `writing-mode:horizontal-tb`, `word-break:keep-all`, `white-space:nowrap`, `flex:0 0 auto`, `overflow:visible` on both panel-head and .s36-title. Cat scaled 0.42 / opacity 0.42, all child animations off.

## PREVIOUS PHASE: Dashboard S35 — Tab/Page Structure Recovery (critical fix)

`static/dashboard.html`.
- **Root cause**: S30/S34 에서 `#page-* { display:flex }` 를 ID 선택자로 직접 지정 → specificity 상 `.page.active` 보다 높아 비활성 페이지도 레이아웃에 계속 참여. 긴 문서처럼 스크롤되는 현상 + AI 탭 활성인데 Home 내용이 위에 남는 현상의 진짜 원인.
- **Fix**: `.page:not(.active){display:none !important}` + `.page.active{display:block !important}` + `#page-*.page.active{display:flex !important;flex-direction:column}` 로 표시 규칙 단일화
- 탭 JS 단일화: cloneNode 로 모든 기존 리스너 제거 후 `activate(target)` 단일 함수만 남김
- 스크롤 정책: per-tab memory 제거, 모든 탭 클릭 = 해당 탭 top (재클릭 포함)
- 고양이: Home panel-hero 내부 only (S34 규칙 유지)
- `.page.active` fadeIn transform 제거

## PREVIOUS: Dashboard S34 — Tab Switching Stabilization + Layout Finalization

`static/dashboard.html` 프론트만.
- 탭 전환 단일 핸들러: `.hud-main` scroller, saved 4-tab scrollTop, 2x rAF 복원, scrollHeight clamp, 재클릭 = top
- `.page.active` fadeIn transform 제거 (iOS jitter 방지)
- 하단 빈 공간: `.hud-main` padding-bottom → `calc(16 + env(safe-area-inset-bottom))`, `.hud-tabs` 높이에 safe-area 포함
- Home CSS order: 상황판 → 주간 → KPI → 시스템 상태 한 줄
- AI CSS order: header → team-overview → ws-grid, tov 더 압축 (stat 13px)
- Intake/Ops order 재확정
- 고양이: Home panel-hero 내부 only, 다른 탭 display:none 강제, scale 0.62

## PREVIOUS: Dashboard S33 — Final Polish (tab scroll memory + density compression)

`static/dashboard.html` 프론트. 백엔드 무변경.
- **탭 스크롤 메모리**: `.hud-main` 기준 탭별 scrollTop Map, 동일 탭 재클릭 = scroll-to-top, rAF 복원 (모바일 Safari 자연스럽게)
- **Home** 15~20% 압축: sb-cell padding/값 축소, 칩 줄 CSS order 우선순위 (premium→b2b→weekly→cta→nl→lead), panel-hero/hl-row/kpi-mini 타이트닝
- **AI 스테이션 2열 실무형**: workflow rail 전체 제거, step 9px flat, grid 22/80/1fr/104, icon 100×74 → 80×56, runs 24→20, 모바일 ws28-c 전폭 row
- **AI 팀 오버뷰** 높이 축소: tov-stat v 17→14, flow/dotmap 더 얇게
- **Intake**: ifn stage v 20→17, lane padding/phrase 타이트닝
- **Ops**: opsr v 18→15, ops-summary val 22→17, ops-card head/row/mini/ratio 전반 축소
- glow/neon 재도입 없음, 정보 삭제 없음 (구조 압축만)

## PREVIOUS: Dashboard S32 — Intake Flow Narrative + Ops Readiness Summary

`static/dashboard.html` Intake + Ops 탭.
- Intake 상단에 `#intake-flow-narrative` 주입: 01 수집 › 02 자산화 › 03 수익화 후보 › 04 연결 stage strip + active 마커 + 5s pulse rail
- Ops 에 `#ops-readiness` 주입: 준비/대기/비어있음 3-count + 6 카테고리 chip (ready/wait/empty 상태어)
- 역할 분리: Intake="정보 흐름", Ops="운영 요약"
- S26 lane/ops-card 디테일 + 카테고리 border-left 는 하위 세부용으로 유지
- Empty state 한국어 문구 2줄 형태 유지

## PREVIOUS: Dashboard S31 — AI Team Overview Panel (top) + 5 Stations (bottom)

`static/dashboard.html` AI 탭만 수정.
- `#page-ai` 상단에 `#team-overview` 주입 (ws-header 아래)
- 3-stat 그리드: 오늘 총 실행 / 가장 바쁨 / 병목 (2px 좌측 color rule, 병목은 unconf > 대기 > 편중 감지)
- `tov-flow`: 5 노드 workflow strip (on/busy/bot/off) + › 구분자
- `tov-dotmap`: 역할별 12-cell 정규화 activity row + last-on tick pulse
- S28 ws-grid 5 스테이션 (3-zone, module icons, live traces) 은 변경 없이 유지

## PREVIOUS: Dashboard S30 — Home as Company Situation Board (weekly promoted)

`static/dashboard.html` Home 탭만 수정. 백엔드 무변경.
- Home `#page-home` 을 flex column + `order` 로 재정렬: Situation Board → 이번 주 핵심 → KPI chip strip → demoted hero-compact
- `.focus-3` / `.strip` 숨김 (situation board 와 중복)
- Hero 포스터 제거: hero-compact 를 dashed 1줄 요약으로 demote
- Weekly highlights 를 Home 핵심 영역으로 승격: rank(01) / #id / hook / monetization bar + score grid row, 빈 상태 2종 한국어
- KPI row 는 thin chip strip 으로 축소 (16px 값)
- 고양이 상태머신 재작성: healthy=pulse+tail+blink, coin-rush=코인 bounce, lean-weekly=translateX+rotate, warning=ear twitch only, alert=grayscale+정지, 랜덤 순찰 없음, pointer-events none
- 모바일: sb-grid 1열, hl-row 2단 grid, kpi 2-col, cat scale 0.55

## PREVIOUS: Dashboard S29 — Direction Lock · Situation Board + Global Tone Reset

`static/dashboard.html` 단일 파일. 백엔드 무변경.
- **Situation Board** 를 Home 최상단에 도입 — "지금 중요한 것 / 병목 / 바쁜 담당" 3-cell judgment panel + 6 business chip row (premium/b2b/newsletter/lead/cta/weekly highlight)
- 기존 hero-compact 는 dashed 보조 요약으로 demote, focus-3/panel-hero/kpi-row 유지
- 판단 로직: db/telegram/x → pending queue → premium candidates → idle → published 순 우선순위
- 병목: DB > 승인 큐 > CTA 미연결 > 초안 대기 > 품질 게이트 > 초안 없음
- 바쁜 담당: AI runs_today 최고치 + 가동 N/5 + 총 M회 요약
- body font-family 를 system-ui 계열로 강제, 숫자만 ui-monospace + tnum
- 카테고리 색 (premium/brief/b2b/newsletter/weekly/cta) 은 ops-card 좌측 2px 힌트로만 축소
- 상태색 (ok/warn/danger/accent/idle) 은 sb-v 와 실제 상태에만
- 탭 계층: Home primary, 나머지 secondary (txt3)
- body::before / hud-corners / grid-overlay / scan-overlay 전부 display:none
- 카드 radial glow / text-shadow / box-shadow 전부 제거 (!important)

## Previous Phases

### S28 — AI Tab Redesign (3-zone workstations)
- 3-zone grid (icon module | info | meta), UI panel icons (로고 X), role-specific live traces
- workflow shared rail + step numbers + flow arrow (Draft→Review→Research→Fact→Trend)
- "다음" 라인으로 협업 전달 경로 명시

### S27 — Demo Mode (?demo=1)
- fetchJSON 을 mock 으로 교체, 4초 틱, DEMO 배지

### S26 — Intake Flow + Ops Operator Board
- lane 에 상태 문구 + mini ratio bar + soft connector + pulse rail
- Ops 카드 head signal bars + 하단 ratio bar + compact empty state

### S25 — AI Workstations Collab + Pipe Trace
- ws-header 협업 요약 배지, 3-stage 파이프 마이크로 트레이스

## S23 — SaaS Backoffice Tone Overhaul

`static/dashboard.html` 단일 파일. 백엔드 무변경.
- ws-header 협업 요약 배지 (`가동 N/5 · 총 M회 · 주도 {role}`)
- 5 역할 카드 하단에 3-stage 파이프 마이크로 트레이스 (wait/live/done/off)
- 역할 차이는 아이콘 모양 + 한국어 상태/담당 문장 + 파이프 단계로 표현, 색은 좌측 3px 힌트만
- live 스테이지 dot 부드러운 펄스 (reduced-motion 존중)

## ⚠️ PREVIOUS PHASE: Dashboard S23 — SaaS Backoffice Tone Overhaul

전역 토큰 재정의 + 전체 컴포넌트 톤 오버라이드. 해커 HUD → 조용한 내부 SaaS 백오피스 룩.
- 팔레트: 네온 시안 → 차분한 sky(#7fb3e6), 배경 중립 슬레이트(#0b0d12), 카테고리 한 단계 낮춤
- 상태/카테고리/accent 분리 확립: ok/warn/danger 는 진짜 상태에만, 카테고리는 2px 좌측 힌트에만
- 모든 컨테이너 border-radius 6px, 1px line border, flat 배경
- 헤더/탭/패널/KPI/hero/ops/ws/lane 전부 text-shadow/box-shadow 제거
- 타이포 위계: uppercase 10px 라벨 + 600 본문 + 24~28px 숫자, letter-spacing -0.4~0.6
- 탭 active: accent 보더탑 + 텍스트 가중치만으로 또렷하게 (글로우 0)
- 고양이 glow/애니메이션 전부 off, opacity 0.6

## ⚠️ PREVIOUS PHASE: Dashboard S22 — Quiet Internal Tool Mode

**방향 전환**: 게임풍 HUD → 조용한 AI 회사 내부 운영툴. `static/dashboard.html` 단일 파일.
- 전역 배경 grid/scanline 제거, 모든 카드 L자 코너 장식 제거, 시그널 바 제거
- 탭: 글로우·언더라인 그림자 제거, 1px accent 언더라인 + 텍스트 색 변화만
- 타이포: 본문 system-ui(-apple/Inter/Pretendard), 숫자만 mono tabular 유지
- 패널/KPI/hero/hero-summary/ops-card/ws-node/lane 전부 평평한 `var(--panel)` + 좌측 3px 카테고리 accent bar 로 통일 (반복감 감소)
- Hero state 라벨 38→30px/700, text-shadow 제거, sub/meta 색 조정
- KPI 숫자 46→40px, amber/magenta 만 카테고리 색, cyan/green 은 중립 txt
- Ops 카드: 상단 색 띠 제거, 좌측 3px bar 로 통일, head 색도 중립 txt
- lucky cat: lucky-pulse/warning glow 제거, coin-rush 만 약한 drop-shadow 유지
- state-chip/empty-pro/ops-summary/attn-band/strip-cell 전부 2px border-radius 로 부드럽게
- 상태색(ok/warn/danger)은 진짜 상태에만 (hero state 라벨, state-chip ready/wait, empty, attention band danger/warn/idle) · 카테고리색은 좌측 bar/카테고리 숫자에만

## ⚠️ PREVIOUS PHASE: Pixel HUD Dashboard S21 — Human-level + Home focus

**S21 — Human-level polish + Home-focused refinement on top of S20. `static/dashboard.html` only.**
- **Hero 위계 강화**: state 라벨 34→38px/800/-0.5px, sub 색을 txt2로 내려 주·보조 분리
- **hero-summary 칩화**: flex → 4-column grid (모바일 2-col), surface-2 배경 + 좌측 2px 카테고리 보더, 라벨 11/600/txt3 · 숫자 20/800/tnum/-0.5px — 숫자+라벨이 한 단위로 스캔됨
- **Weekly Highlights를 홈 중심으로 승격** (`.panel-hero`): accent 알파 테두리, 인셋 글로우, 헤더 ◆ 강조, hl-item 크기 및 보더 강화
- **Lucky cat warning 분기 연결**: 텔레그램/X 미설정 시 cat이 `warning` (felow paw/tail, amber 글로우). alert/idle/coin-rush/lean-weekly/healthy 상태머신에 warning 합류
- 이전 S21 (a) 단계에서 이미 적용: semantic 토큰 + --surface-2/--rail, tnum 숫자 피처, tab 활성 강화, 새 컴포넌트(attn-band/hero-spark/ops-summary/empty-pro/worker-rail/role-badge/ws-status/mini-trace/stage-dot), Home hero-spark + attention-band JS, AI 워커 프레즌스 (working/off 상태 + 역할 배지 + 마이크로 트레이스)
- 백엔드/스키마/승인 워크플로/자동 발행 변경 없음

## ⚠️ PREVIOUS PHASE: Pixel HUD Dashboard Final Polish (S20)

**S20 — Final product polish on top of S18(rebuild)+S19(refinement). `static/dashboard.html` only.**
- **Color tokens redesigned with semantic separation**: single brand `--accent`, status colors (`--ok/--warn/--danger`) reserved for real system state, six lite category tokens (`--cat-premium/-brief/-b2b/-news/-weekly/-cta`) for section identity. Status and category colors no longer compete.
- **Glow / effect intensity reduced**: scanline 0.012→0.008, grid lines 0.045→0.030, text-shadow 14px·0.4→8px·0.25, bar glow 8px→4px, ws-icon radial 0.18→0.10. Less amateur-HUD, more polished product.
- **Typography for scan speed**: small labels above large numbers enlarged + brightened (KPI label 11→13px, txt3→txt2/600), weights bumped (kpi-val/strip-val/ws-role 700→800), letter-spacing tightened to 0.2–0.3px (Korean-friendly), uppercase removed.
- **AI icons replaced** with role-distinct pixel HUD shapes: document+cursor / magnifier+tick / radar sweep / stamp+check / waveform+pulse. Single accent color, distinction by shape.
- **Empty-state compression**: unified `▢` chip with dashed border for empty/ops-empty/lane-empty. Ops cards auto-collapse to `.is-empty` (smaller padding, dimmed big number, mini hidden) when zero.
- **Home hierarchy refined**: new hero summary line (초안·승인 대기·프리미엄·B2B), Weekly Highlights moved up above strip, hero meta separated by dashed border.
- **Active tab strengthened**: weight 700→800, icon 20→22px, top-line 24→32px, subtle background gradient.
- Lucky cat S19 state machine preserved unchanged.

Branches synced: `claude/extract-prediction-time-n82UK` and `claude/premium-control-room-ui-LJFba`.

## ⚠️ PREVIOUS PHASE: Pixel HUD Dashboard Refinement (S19)

**S19 — Refinement on top of S18 dashboard (`static/dashboard.html` only):**
- Full Korean UI localization (chrome / Home / AI / Intake / Ops, all operator-facing text)
- Mobile readability scale-up: base font 13→15px, KPI numbers 26→**46px**, Ops big 18→**30px**, AI runs 18→**30px**, Hero state 22→**34px**
- Lucky cat → system-aware state machine: `alert` (db down, ear twitch only) / `idle` (slow tail) / `coin-rush` (premium·b2b candidates → fast coin + gold glow) / `lean-weekly` (highlights → tilt toward weekly panel) / `healthy` (lucky-pulse + blink + tail)
- Removed decorative random patrol; cat now reflects real signals from `/control/status` + `/control/business-summary`
- No backend / schema / test changes

## ⚠️ PREVIOUS PHASE: Pixel HUD Dashboard Rebuild (S18)

**DO NOT re-implement premium/b2b/email/lead base services. They are built and tested.**
**DO NOT revert to portrait/Live2D dashboard — it has been replaced with a pixel HUD.**

Session 18 — Full dashboard rebuild from scratch:
- New `static/dashboard.html` (1128 lines) — pixel-digital control room, no images, no Live2D
- 4 rebuilt pages: Home / AI Workstations / Intake Flow / Ops Monitoring
- Lucky cat SVG mascot on Home (blink/tail/paw/patrol/lucky-pulse, prefers-reduced-motion safe)
- Backend: `/control/business-summary` aggregates premium/brief/b2b/newsletter/weekly/cta perf
- 5 AI workstation nodes with role-specific motion (typing/blink/scan/check/pulse)
- 6 Ops cards surface entire business stack with monetization-ready signals
- `static/live2d.js` deleted; old dashboard preserved as `dashboard.html.backup`

Session 15–17 (still locked):
- **B2B sample report** — `generate_sample_report()`, `/b2b report <id> [save|export]`
- **Brief offer layer** — `BriefOfferService`, `/brief` (8 subcommands), 3 new columns
- **Newsletter routine** — `NewsletterRoutineService`, `/newsletter` (7 subcommands)
- **Weekly report** — `WeeklyReportService`, `/weekly` (summary/view/export)
- **CTA copy library** — `CtaCopyService`, `CtaCopy` model, `/cta copy` (9 subcommands), draft linking
- **CTA copy perf tracking** — `get_copy_perf`, `get_all_perf`, `/cta perf` (3 subcommands)
- **Weekly CTA perf section** — `_cta_perf_summary()`, `/weekly view`·`/weekly export` 통합
- 896 tests passing, all flows protected

---

## Current Phase Detail

**Session 15–16 — Business Operating Layers + CTA Copy + Perf** (complete)

What was built:
1. `app/services/b2b_candidate_service.py` — `generate_sample_report`, `format_sample_report`, `save_report_to_note`
2. `app/services/brief_offer_service.py` — NEW (BriefOfferService)
3. `app/services/newsletter_routine_service.py` — NEW (NewsletterRoutineService)
4. `app/services/weekly_report_service.py` — NEW (WeeklyReportService)
5. `app/services/cta_copy_service.py` — NEW (CtaCopyService + perf tracking)
6. `app/models/content.py` — `CtaCopy` model + 4 columns (`brief_type`, `brief_price_tier`, `brief_summary_note`, `cta_copy_id`)
7. `app/db.py` — 4 migration entries
8. `app/telegram_bot.py` — `/b2b report`, `/brief`, `/newsletter`, `/weekly`, `/lead export`, `/cta copy`, `/cta link/unlink`, `/cta perf`
9. Tests: `test_cta_copy.py` (52), `test_brief_offer.py` (38), `test_newsletter_routine.py` (29), `test_weekly_report.py` (26), `test_b2b_candidate.py` (+20)

---

## Closed (Done and Locked)

| Phase | Area | Status |
|-------|------|--------|
| — | Orchestrator Steps 1–7 | Locked |
| — | Layer 1 core flow (ContentRequest → XPublisher) | Locked |
| — | Telegram approval callbacks (approve/reject/defer/regenerate) | Locked |
| — | PostQueue approval gate (notification-only, no auto-publish) | Locked |
| — | hint / perf / operator workflow | Locked |
| — | 5-criteria quality framework | Locked |
| — | Provider integrations (Grok, Perplexity, Gemini, OpenAI, Anthropic) | Locked |
| — | /draft fast-path | Locked |
| — | Posting pack standardization | Locked |
| — | /queue remove, /queue clear, /queue view | Locked |
| — | /monitor off/on/status | Locked |
| — | Idle pipeline reminder | Locked |
| — | /status improvements | Locked |
| — | Reply monitor inline button | Locked |
| — | Rate limiter settings externalization | Locked |
| — | OpenAI SYSTEM_PROMPT refresh | Locked |
| — | Reviewer quality_flags | Locked |
| 12 | Growth Intelligence Bundle | Locked |
| 13–17 | news_regen, hygiene, ops recovery, critical flows, release gate | Locked |
| **18** | **Control Room dashboard + /menu** | **Locked** |
| **18-I** | **Material rebuild: split-stage hero, standalone AI cards** | **Locked** |
| **S15** | **B2B sample report (/b2b report)** | **Locked** |
| **S15** | **Brief offer layer (/brief, BriefOfferService)** | **Locked** |
| **S15** | **Newsletter routine (/newsletter, NewsletterRoutineService)** | **Locked** |
| **S15** | **Weekly report (/weekly, WeeklyReportService)** | **Locked** |
| **S15** | **CTA copy library (/cta copy, CtaCopyService, CtaCopy model)** | **Locked** |
| **S16** | **CTA copy perf tracking (/cta perf)** | **Locked** |
| **S17** | **Weekly CTA perf section (/weekly view·export)** | **Locked** |
| **S18** | **Pixel HUD dashboard rebuild (4 pages + mascot + business-summary)** | **Locked** |

---

## Deferred (Do Not Build Without Explicit Operator Directive)

- Auto-posting of any kind — permanently excluded
- Image / video generation
- ML fine-tuning / embedding store / RAG
- Multi-user support
- Redis / task queue / Postgres migration
- Payment flow / checkout
- Full email sender
- Dashboard analytics / BI charts
- A/B testing / page builder

---

## Next Candidates

**System is fully operator-ready. Nothing urgent is missing.**
896 tests passing, all flows protected.
Full operating layer stack: premium, B2B, brief, newsletter, lead, weekly report, CTA copy library + perf.

---

## Last Updated

- Date: 2026-04-07 (session 18 — Pixel HUD Dashboard Rebuild)
- Branch: claude/extract-prediction-time-n82UK (aligned to claude/premium-control-room-ui-LJFba)
- Key commits:
  - Pixel HUD dashboard rebuild (dashboard.html + lucky cat mascot)
  - `dd0190a` — /control/business-summary 단일 집계 엔드포인트
  - `8985b62` — Weekly CTA perf section (_cta_perf_summary + /weekly 통합)
  - `7cb6e21` — CTA copy perf tracking (/cta perf + tests)
  - `9e541e5` — CTA copy library (/cta copy + draft linking)
  - `70a186f` — Weekly operating report (/weekly)
  - `da09c92` — Newsletter/lead routine (/newsletter, /lead export)
  - `22e242a` — Brief offer layer (/brief)
  - `1563849` — B2B sample report (/b2b report)
- Run `git log --oneline -10` to see recent commits
