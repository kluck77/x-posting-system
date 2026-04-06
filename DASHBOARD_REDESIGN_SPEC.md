# DASHBOARD_REDESIGN_SPEC.md
# 대시보드 전면 재설계 구현 지시서
# 이 파일은 Claude Code가 읽고 코드를 짜는 설계도다
# 기준: 2026-04-06

---

## 핵심 전제

GPT 지시문 요약: "기존 레이아웃에 이미지 붙이는 것 FAIL. 진짜 Control Room으로 재설계."
이 지시를 실현하는 방법은 하나다:

> **기존 dashboard HTML을 수정하지 말고, 새 파일로 처음부터 다시 만든다.**

---

## STEP 0: 준비 작업 (코딩 전 반드시)

```
1. 현재 대시보드 HTML 파일 경로 확인
2. 캐릭터 이미지 파일 전부 경로 확인
   - draftwriter.png
   - reviewer.png  
   - researcher.png
   - factchecker.png (있으면)
   - trendhunter.png (있으면)
3. 기존 파일을 .backup 확장자로 복사 후 보존
4. 새 파일 이름: dashboard_v2.html (또는 index.html 교체)
```

---

## STEP 1: 전체 디자인 시스템 (CSS Variables)

새 파일 상단에 이 CSS 변수 시스템을 먼저 선언한다.
이것이 전체 UI의 DNA다. 절대 임의로 색상 넣지 말 것.

```css
:root {
  /* === 배경 레이어 === */
  --bg-void: #050508;           /* 최심층 배경 */
  --bg-deep: #0a0a12;           /* 씬 배경 */
  --bg-surface: #0f0f1a;        /* 카드 배경 */
  --bg-raised: #141420;         /* 높은 요소 */
  --bg-panel: rgba(20, 20, 36, 0.85); /* 패널 (blur 효과용) */

  /* === 테두리 === */
  --border-subtle: rgba(255,255,255,0.06);
  --border-normal: rgba(255,255,255,0.10);
  --border-accent: rgba(99, 102, 241, 0.35);

  /* === 색상 시스템 === */
  --indigo: #6366f1;
  --indigo-dim: rgba(99, 102, 241, 0.15);
  --green: #22c55e;
  --green-dim: rgba(34, 197, 94, 0.15);
  --amber: #f59e0b;
  --amber-dim: rgba(245, 158, 11, 0.15);
  --red: #ef4444;
  --red-dim: rgba(239, 68, 68, 0.15);
  --cyan: #06b6d4;
  --cyan-dim: rgba(6, 182, 212, 0.12);

  /* === 텍스트 === */
  --text-primary: rgba(255,255,255,0.92);
  --text-secondary: rgba(255,255,255,0.55);
  --text-muted: rgba(255,255,255,0.30);
  --text-accent: #a5b4fc;

  /* === 글로우 === */
  --glow-indigo: 0 0 24px rgba(99,102,241,0.25);
  --glow-green: 0 0 20px rgba(34,197,94,0.20);
  --glow-amber: 0 0 20px rgba(245,158,11,0.20);
  --glow-red: 0 0 20px rgba(239,68,68,0.20);

  /* === 타이포그래피 === */
  --font-mono: 'JetBrains Mono', 'Fira Code', 'Courier New', monospace;
  --font-sans: -apple-system, BlinkMacSystemFont, 'Inter', 'Segoe UI', sans-serif;

  /* === 레이아웃 === */
  --radius-sm: 8px;
  --radius-md: 12px;
  --radius-lg: 16px;
  --radius-xl: 20px;
  --nav-height: 64px;
  --safe-bottom: env(safe-area-inset-bottom, 0px);
}
```

---

## STEP 2: 전체 HTML 뼈대

```html
<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
  <title>X System — Control Room</title>
  <!-- Google Fonts: Inter + JetBrains Mono -->
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="dashboard.css">
</head>
<body>

  <!-- 전체 배경 분위기 레이어 -->
  <div class="bg-atmosphere">
    <div class="bg-orb bg-orb--indigo"></div>
    <div class="bg-orb bg-orb--cyan"></div>
    <div class="bg-grid"></div>
  </div>

  <!-- 상단 헤더 -->
  <header class="topbar">
    <div class="topbar__brand">
      <span class="topbar__icon">🦊</span>
      <span class="topbar__name">X System</span>
      <span class="topbar__badge">CONTROL ROOM</span>
    </div>
    <div class="topbar__time" id="topbarTime"></div>
    <button class="topbar__refresh" id="refreshBtn">↻</button>
  </header>

  <!-- 탭 컨텐츠 영역 -->
  <main class="main-content">
    <!-- TAB 1: HOME -->
    <section class="tab-pane active" id="tab-home">
      <!-- [STEP 3 참고] -->
    </section>

    <!-- TAB 2: AI -->
    <section class="tab-pane" id="tab-ai">
      <!-- [STEP 4 참고] -->
    </section>

    <!-- TAB 3: INTAKE -->
    <section class="tab-pane" id="tab-intake">
      <!-- [STEP 5 참고] -->
    </section>

    <!-- TAB 4: OPS -->
    <section class="tab-pane" id="tab-ops">
      <!-- [STEP 6 참고] -->
    </section>
  </main>

  <!-- 하단 탭 네비게이션 -->
  <nav class="bottom-nav">
    <button class="nav-item active" data-tab="home">
      <span class="nav-item__icon">🏠</span>
      <span class="nav-item__label">Status</span>
    </button>
    <button class="nav-item" data-tab="ai">
      <span class="nav-item__icon">🤖</span>
      <span class="nav-item__label">AI</span>
    </button>
    <button class="nav-item" data-tab="intake">
      <span class="nav-item__icon">📥</span>
      <span class="nav-item__label">Intake</span>
    </button>
    <button class="nav-item" data-tab="ops">
      <span class="nav-item__icon">⚙️</span>
      <span class="nav-item__label">Ops</span>
    </button>
  </nav>

  <script src="dashboard.js"></script>
</body>
</html>
```

---

## STEP 3: HOME 탭 — Unified Hero Control Room

**핵심**: 스택된 카드 금지. 하나의 씬으로 통합.

```html
<!-- HOME TAB INNER HTML -->
<div class="hero-scene">
  
  <!-- 배경: 별빛 파티클 -->
  <canvas class="hero-particles" id="heroParticles"></canvas>

  <!-- 메인 어시스턴트 캐릭터 (DraftWriter — 가장 큰 캐릭터) -->
  <div class="hero-character hero-character--main" id="mainChar">
    <div class="hero-character__halo"></div>
    <img src="./assets/draftwriter.png" alt="DraftWriter" 
         class="hero-character__img char-idle">
    <div class="hero-character__desk-glow"></div>
  </div>

  <!-- 미니 워커들 (돌아다니는 작은 캐릭터들) -->
  <div class="mini-workers" id="miniWorkers">
    <div class="mini-worker" id="worker-reviewer" style="--walk-duration:11s; --walk-delay:0s;">
      <img src="./assets/reviewer.png" alt="" class="mini-worker__img">
    </div>
    <div class="mini-worker" id="worker-researcher" style="--walk-duration:14s; --walk-delay:2s;">
      <img src="./assets/researcher.png" alt="" class="mini-worker__img">
    </div>
  </div>

  <!-- 오버레이 정보 패널들 (씬 위에 떠있는 느낌) -->
  <div class="hero-overlay">

    <!-- 상태 표시 (좌상단) -->
    <div class="scene-panel scene-panel--status">
      <div class="scene-panel__title">SYSTEM</div>
      <div class="status-dots" id="statusDots">
        <div class="status-dot" data-key="db">
          <span class="status-dot__led" id="dot-db"></span>
          <span class="status-dot__label">DB</span>
        </div>
        <div class="status-dot" data-key="telegram">
          <span class="status-dot__led" id="dot-telegram"></span>
          <span class="status-dot__label">TG</span>
        </div>
        <div class="status-dot" data-key="x">
          <span class="status-dot__led" id="dot-x"></span>
          <span class="status-dot__label">X</span>
        </div>
      </div>
    </div>

    <!-- 오늘 할당량 (우상단) -->
    <div class="scene-panel scene-panel--quota">
      <div class="scene-panel__title">TODAY</div>
      <div class="quota-mini">
        <div class="quota-mini__row">
          <span>Drafts</span>
          <span id="quotaDrafts" class="quota-mini__val">—</span>
        </div>
        <div class="quota-mini__row">
          <span>Posts</span>
          <span id="quotaPosts" class="quota-mini__val">—</span>
        </div>
      </div>
    </div>

    <!-- 헤드라인 (하단 중앙) -->
    <div class="hero-headline">
      <div class="hero-headline__sub">AI Content Operations</div>
      <div class="hero-headline__main">Control Room</div>
      <div class="hero-headline__activity" id="heroActivity">대기 중…</div>
    </div>

  </div>
</div>

<!-- 스크롤 영역: 최근 활동 -->
<div class="home-feed">
  <div class="feed-header">
    <span class="feed-header__title">RECENT ACTIVITY</span>
  </div>
  <div class="feed-list" id="feedList">
    <div class="feed-empty">— 없음 —</div>
  </div>
</div>
```

---

## STEP 4: AI 탭 — 워크스테이션 씬

**핵심**: 카드+초상화 금지. 각 AI가 실제로 일하는 워크스테이션처럼.

```html
<!-- AI TAB INNER HTML -->
<div class="ai-page">
  <div class="page-header">
    <h2 class="page-header__title">AI 워크스테이션</h2>
    <span class="page-header__sub">오늘 초안 기준</span>
  </div>

  <div class="workstations">

    <!-- 각 워크스테이션 카드 패턴 -->
    <!-- DraftWriter -->
    <div class="workstation" data-role="draftwriter" data-status="mock">
      <div class="workstation__scene">
        <!-- 배경 그리드/화면 효과 -->
        <div class="workstation__screen">
          <div class="workstation__screen-lines">
            <div class="screen-line"></div>
            <div class="screen-line"></div>
            <div class="screen-line"></div>
          </div>
        </div>
        <!-- 캐릭터: 씬 안에 임베드 -->
        <div class="workstation__char-wrap">
          <img src="./assets/draftwriter.png" 
               alt="DraftWriter"
               class="workstation__char char-idle"
               onerror="this.style.display='none'">
          <!-- 작업 중 파티클 (타이핑 이펙트) -->
          <div class="work-particles" id="wp-draftwriter"></div>
        </div>
        <!-- 씬 조명 -->
        <div class="workstation__light"></div>
      </div>
      <div class="workstation__info">
        <div class="workstation__header">
          <span class="workstation__role">DraftWriter</span>
          <span class="workstation__badge workstation__badge--mock">mock</span>
        </div>
        <div class="workstation__desc">초안 작성 · 5-criteria 자가검증</div>
        <div class="workstation__stats">
          <div class="ws-stat">
            <span class="ws-stat__num" id="ws-dw-count">0</span>
            <span class="ws-stat__label">오늘</span>
          </div>
          <div class="ws-stat">
            <span class="ws-stat__status" id="ws-dw-status">대기</span>
          </div>
        </div>
      </div>
    </div>

    <!-- Reviewer, Researcher, FactChecker, TrendHunter 동일 패턴으로 반복 -->
    <!-- 각각 data-role, 이미지 경로, id만 변경 -->

  </div>
</div>
```

---

## STEP 5: CSS 핵심 애니메이션 (반드시 포함)

```css
/* =============================
   CHARACTER ANIMATIONS
   ============================= */

/* Idle float: 위아래 부드럽게 */
@keyframes charFloat {
  0%, 100% { transform: translateY(0px); }
  50%       { transform: translateY(-8px); }
}

/* Breathing: 미세한 scale */
@keyframes charBreathe {
  0%, 100% { transform: scaleY(1) scaleX(1); }
  40%       { transform: scaleY(1.015) scaleX(0.995); }
  60%       { transform: scaleY(0.99) scaleX(1.005); }
}

/* Blink: 눈 깜빡임 (::after pseudo로 구현) */
@keyframes charBlink {
  0%, 94%, 100% { transform: scaleY(1); }
  96%            { transform: scaleY(0.05); }
}

/* 조합 적용 */
.char-idle {
  animation:
    charFloat   4s ease-in-out infinite,
    charBreathe 5s ease-in-out infinite;
  will-change: transform;
  transform-origin: bottom center;
}

/* 각 캐릭터마다 delay 다르게 */
.workstation:nth-child(1) .char-idle { animation-delay: 0s, 0s; }
.workstation:nth-child(2) .char-idle { animation-delay: -1.5s, -2s; }
.workstation:nth-child(3) .char-idle { animation-delay: -3s, -1s; }
.workstation:nth-child(4) .char-idle { animation-delay: -0.5s, -3s; }
.workstation:nth-child(5) .char-idle { animation-delay: -2.5s, -0.5s; }

/* =============================
   MINI WALKERS (Home 탭)
   ============================= */
@keyframes walkRight {
  0%   { transform: translateX(0) scaleX(1); }
  48%  { transform: translateX(calc(100vw - 80px)) scaleX(1); }
  50%  { transform: translateX(calc(100vw - 80px)) scaleX(-1); }
  98%  { transform: translateX(0) scaleX(-1); }
  100% { transform: translateX(0) scaleX(1); }
}

.mini-worker {
  position: absolute;
  bottom: 20px;
  left: 10px;
  width: 44px;
  height: 44px;
  animation: walkRight var(--walk-duration, 12s) linear infinite;
  animation-delay: var(--walk-delay, 0s);
  will-change: transform;
}

.mini-worker__img {
  width: 100%;
  height: 100%;
  object-fit: contain;
  filter: drop-shadow(0 4px 8px rgba(99,102,241,0.4));
}

/* =============================
   WORKSTATION CARD
   ============================= */
.workstation {
  background: var(--bg-surface);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-lg);
  overflow: hidden;
  transition: transform 0.25s ease, border-color 0.25s ease, box-shadow 0.25s ease;
  position: relative;
}

.workstation:hover,
.workstation:active {
  transform: translateY(-3px);
  border-color: var(--border-accent);
  box-shadow: var(--glow-indigo);
}

/* 워크스테이션 씬 영역 */
.workstation__scene {
  position: relative;
  height: 160px;
  background: linear-gradient(180deg, #0a0a1a 0%, #111128 100%);
  overflow: hidden;
}

/* 캐릭터를 씬에 embed - 하단에 자연스럽게 위치 */
.workstation__char-wrap {
  position: absolute;
  bottom: 0;
  right: 16px;
  width: 100px;
  height: 140px;
  display: flex;
  align-items: flex-end;
  justify-content: center;
}

.workstation__char {
  max-width: 100%;
  max-height: 100%;
  object-fit: contain;
  /* 이미지 하단에 자연스러운 페이드 */
  -webkit-mask-image: linear-gradient(to top, transparent 0%, black 15%);
  mask-image: linear-gradient(to top, transparent 0%, black 15%);
  filter: drop-shadow(0 -4px 16px rgba(99,102,241,0.3));
}

/* 화면 스캔라인 효과 */
.workstation__screen {
  position: absolute;
  inset: 0;
  background:
    repeating-linear-gradient(
      0deg,
      transparent,
      transparent 2px,
      rgba(99,102,241,0.03) 2px,
      rgba(99,102,241,0.03) 4px
    );
  pointer-events: none;
}

/* 씬 조명: 캐릭터 뒤에서 오는 빛 */
.workstation__light {
  position: absolute;
  bottom: -20px;
  right: 30px;
  width: 80px;
  height: 80px;
  background: radial-gradient(circle, rgba(99,102,241,0.25) 0%, transparent 70%);
  pointer-events: none;
}

/* 작업 파티클 (타이핑 이펙트) */
@keyframes particleFly {
  0%   { opacity: 1; transform: translateY(0) translateX(0); }
  100% { opacity: 0; transform: translateY(-30px) translateX(10px); }
}

.work-particle {
  position: absolute;
  width: 3px;
  height: 3px;
  border-radius: 50%;
  background: var(--indigo);
  animation: particleFly 1.2s ease-out infinite;
}

/* status별 캐릭터 상태 */
.workstation[data-status="active"] .workstation__char {
  filter: drop-shadow(0 -4px 20px rgba(34,197,94,0.4));
}
.workstation[data-status="mock"] .workstation__char {
  filter: grayscale(40%) drop-shadow(0 -4px 12px rgba(99,102,241,0.2));
}
.workstation[data-status="error"] .workstation__char {
  filter: drop-shadow(0 -4px 16px rgba(239,68,68,0.4));
}

/* =============================
   HERO SCENE (Home 탭)
   ============================= */
.hero-scene {
  position: relative;
  height: 52vh;
  min-height: 280px;
  max-height: 420px;
  overflow: hidden;
  background: linear-gradient(180deg, #070710 0%, #0d0d1e 100%);
}

.hero-character--main {
  position: absolute;
  bottom: 0;
  left: 50%;
  transform: translateX(-50%);
  width: 160px;
  z-index: 2;
}

.hero-character__img {
  width: 100%;
  -webkit-mask-image: linear-gradient(to top, transparent 0%, black 12%);
  mask-image: linear-gradient(to top, transparent 0%, black 12%);
  filter: drop-shadow(0 0 32px rgba(99,102,241,0.5));
}

/* 캐릭터 뒤 후광 */
.hero-character__halo {
  position: absolute;
  bottom: 20px;
  left: 50%;
  transform: translateX(-50%);
  width: 120px;
  height: 60px;
  background: radial-gradient(ellipse, rgba(99,102,241,0.35) 0%, transparent 70%);
  filter: blur(12px);
  animation: haloPulse 3s ease-in-out infinite;
}

@keyframes haloPulse {
  0%, 100% { opacity: 0.6; transform: translateX(-50%) scaleX(1); }
  50%       { opacity: 1; transform: translateX(-50%) scaleX(1.15); }
}

/* 씬 패널 (반투명 글래스) */
.scene-panel {
  position: absolute;
  background: rgba(10, 10, 20, 0.75);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
  padding: 10px 14px;
  z-index: 3;
}

.scene-panel--status {
  top: 16px;
  left: 16px;
}

.scene-panel--quota {
  top: 16px;
  right: 16px;
}

.scene-panel__title {
  font-family: var(--font-mono);
  font-size: 9px;
  letter-spacing: 0.12em;
  color: var(--text-muted);
  margin-bottom: 6px;
}

/* 히어로 헤드라인 */
.hero-headline {
  position: absolute;
  bottom: 20px;
  left: 50%;
  transform: translateX(-50%);
  text-align: center;
  z-index: 3;
  white-space: nowrap;
}

.hero-headline__sub {
  font-size: 10px;
  font-family: var(--font-mono);
  letter-spacing: 0.15em;
  color: var(--text-accent);
  margin-bottom: 2px;
}

.hero-headline__main {
  font-size: 20px;
  font-weight: 700;
  color: var(--text-primary);
  letter-spacing: -0.02em;
}

.hero-headline__activity {
  font-size: 11px;
  color: var(--text-muted);
  margin-top: 4px;
}

/* =============================
   STATUS DOTS
   ============================= */
.status-dots {
  display: flex;
  gap: 10px;
}

.status-dot {
  display: flex;
  align-items: center;
  gap: 5px;
}

.status-dot__led {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--text-muted);
  transition: background 0.3s;
}

.status-dot__led.is-ok    { background: var(--green); box-shadow: 0 0 6px var(--green); }
.status-dot__led.is-warn  { background: var(--amber); box-shadow: 0 0 6px var(--amber); }
.status-dot__led.is-error { background: var(--red);   box-shadow: 0 0 6px var(--red);
  animation: ledBlink 1.5s ease-in-out infinite; }

@keyframes ledBlink {
  0%, 100% { opacity: 1; }
  50%       { opacity: 0.3; }
}

.status-dot__label {
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--text-secondary);
}

/* =============================
   BACKGROUND ATMOSPHERE
   ============================= */
.bg-atmosphere {
  position: fixed;
  inset: 0;
  z-index: -1;
  overflow: hidden;
  pointer-events: none;
}

.bg-orb {
  position: absolute;
  border-radius: 50%;
  filter: blur(80px);
  opacity: 0.12;
}

.bg-orb--indigo {
  width: 400px;
  height: 400px;
  background: var(--indigo);
  top: -100px;
  right: -100px;
  animation: orbDrift 20s ease-in-out infinite alternate;
}

.bg-orb--cyan {
  width: 300px;
  height: 300px;
  background: var(--cyan);
  bottom: -80px;
  left: -80px;
  animation: orbDrift 25s ease-in-out infinite alternate-reverse;
}

@keyframes orbDrift {
  0%   { transform: translate(0, 0); }
  100% { transform: translate(30px, 20px); }
}

/* 미세 그리드 */
.bg-grid {
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(rgba(255,255,255,0.025) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255,255,255,0.025) 1px, transparent 1px);
  background-size: 40px 40px;
}

/* =============================
   TOPBAR
   ============================= */
.topbar {
  position: sticky;
  top: 0;
  z-index: 100;
  height: var(--nav-height);
  display: flex;
  align-items: center;
  padding: 0 16px;
  background: rgba(5, 5, 10, 0.90);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  border-bottom: 1px solid var(--border-subtle);
  gap: 8px;
}

.topbar__brand { display: flex; align-items: center; gap: 8px; flex: 1; }
.topbar__icon  { font-size: 18px; }
.topbar__name  { font-weight: 700; font-size: 15px; color: var(--text-primary); }
.topbar__badge {
  font-family: var(--font-mono);
  font-size: 9px;
  letter-spacing: 0.1em;
  color: var(--text-accent);
  background: var(--indigo-dim);
  border: 1px solid var(--border-accent);
  border-radius: 4px;
  padding: 2px 6px;
}

.topbar__time {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-muted);
}

.topbar__refresh {
  background: none;
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  color: var(--text-secondary);
  width: 32px;
  height: 32px;
  font-size: 14px;
  cursor: pointer;
  transition: all 0.2s;
}
.topbar__refresh:active { transform: rotate(180deg); }

/* =============================
   BOTTOM NAV
   ============================= */
.bottom-nav {
  position: fixed;
  bottom: 0;
  left: 0;
  right: 0;
  z-index: 100;
  height: calc(60px + var(--safe-bottom));
  padding-bottom: var(--safe-bottom);
  display: flex;
  background: rgba(5, 5, 10, 0.95);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  border-top: 1px solid var(--border-subtle);
}

.nav-item {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 3px;
  background: none;
  border: none;
  color: var(--text-muted);
  cursor: pointer;
  transition: color 0.2s;
  padding-top: 8px;
}

.nav-item.active {
  color: var(--indigo);
}

.nav-item.active .nav-item__icon {
  filter: drop-shadow(0 0 6px rgba(99,102,241,0.6));
}

.nav-item__icon  { font-size: 20px; }
.nav-item__label { font-size: 10px; font-family: var(--font-mono); letter-spacing: 0.05em; }

/* =============================
   MAIN CONTENT / TABS
   ============================= */
.main-content {
  padding-bottom: calc(60px + var(--safe-bottom) + 16px);
}

.tab-pane { display: none; }
.tab-pane.active { display: block; }

/* =============================
   REDUCED MOTION
   ============================= */
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    transition-duration: 0.01ms !important;
  }
}
```

---

## STEP 6: JavaScript 핵심 로직

```javascript
// dashboard.js

// === 탭 전환 ===
document.querySelectorAll('.nav-item').forEach(btn => {
  btn.addEventListener('click', () => {
    const tab = btn.dataset.tab;
    document.querySelectorAll('.nav-item').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById('tab-' + tab).classList.add('active');
  });
});

// === 시간 표시 ===
function updateTime() {
  const el = document.getElementById('topbarTime');
  if (!el) return;
  const now = new Date();
  el.textContent = now.toLocaleTimeString('ko-KR', {
    hour: '2-digit', minute: '2-digit', second: '2-digit',
    timeZone: 'Asia/Seoul'
  }) + ' KST';
}
setInterval(updateTime, 1000);
updateTime();

// === API 데이터 로드 ===
const API_BASE = window.location.origin;

async function loadStatus() {
  try {
    const res = await fetch(API_BASE + '/health');
    const data = await res.json();
    updateStatusDots(data);
  } catch(e) {
    console.warn('Status load failed:', e);
  }
}

async function loadUsage() {
  try {
    const res = await fetch(API_BASE + '/usage');
    const data = await res.json();
    const draftsEl = document.getElementById('quotaDrafts');
    const postsEl  = document.getElementById('quotaPosts');
    if (draftsEl) draftsEl.textContent =
      `${data.drafts?.used ?? 0} / ${data.drafts?.limit ?? 5}`;
    if (postsEl) postsEl.textContent =
      `${data.posts?.used ?? 0} / ${data.posts?.limit ?? 10}`;
  } catch(e) {
    console.warn('Usage load failed:', e);
  }
}

function updateStatusDots(healthData) {
  const map = {
    'dot-db':       healthData.database_ok,
    'dot-telegram': healthData.telegram_configured,
    'dot-x':        healthData.x_configured,
  };
  Object.entries(map).forEach(([id, ok]) => {
    const el = document.getElementById(id);
    if (!el) return;
    el.className = 'status-dot__led ' + (ok ? 'is-ok' : 'is-error');
  });
}

// === 워크 파티클 생성 ===
function createWorkParticle(containerId) {
  const container = document.getElementById(containerId);
  if (!container) return;
  const p = document.createElement('div');
  p.className = 'work-particle';
  p.style.left = Math.random() * 60 + 'px';
  p.style.bottom = Math.random() * 40 + 'px';
  p.style.animationDelay = Math.random() * 1.2 + 's';
  container.appendChild(p);
  setTimeout(() => p.remove(), 1500);
}

// 워크스테이션마다 주기적으로 파티클 생성
['wp-draftwriter', 'wp-reviewer', 'wp-researcher'].forEach(id => {
  setInterval(() => createWorkParticle(id), 800 + Math.random() * 600);
});

// === 초기 로드 ===
loadStatus();
loadUsage();

// 새로고침 버튼
document.getElementById('refreshBtn')?.addEventListener('click', () => {
  loadStatus();
  loadUsage();
});
```

---

## STEP 7: Intake 탭 — Naver 센터피스

```html
<!-- INTAKE TAB INNER HTML -->
<div class="intake-page">
  <div class="page-header">
    <h2 class="page-header__title">인풋 & 플로우</h2>
    <span class="page-header__sub">뉴스 수집 · 초안 흐름</span>
  </div>

  <!-- Naver 센터피스 (크게, 위계 최상위) -->
  <div class="naver-centerpiece">
    <div class="naver-centerpiece__logo">
      <span class="naver-logo-n">N</span>
      <span class="naver-logo-text">AVER</span>
    </div>
    <div class="naver-centerpiece__gauge">
      <svg class="radial-gauge" viewBox="0 0 120 120">
        <circle class="radial-gauge__track" cx="60" cy="60" r="50"
                stroke-dasharray="314" stroke-dashoffset="0"/>
        <circle class="radial-gauge__fill" cx="60" cy="60" r="50"
                stroke-dasharray="314" stroke-dashoffset="314"
                id="naverGaugeFill"/>
      </svg>
      <div class="radial-gauge__label">
        <div class="radial-gauge__pct" id="naverPct">0.0%</div>
        <div class="radial-gauge__sub">사용률</div>
      </div>
    </div>
    <div class="naver-centerpiece__count">
      <span id="naverCount">0</span>
      <span class="naver-centerpiece__total"> / 25,000</span>
    </div>
  </div>

  <!-- 파이프라인 플로우 -->
  <div class="pipeline-flow">
    <div class="pipeline-step is-active" data-step="source">
      <div class="pipeline-step__icon">📡</div>
      <div class="pipeline-step__label">Source</div>
    </div>
    <div class="pipeline-arrow">—</div>
    <div class="pipeline-step" data-step="research">
      <div class="pipeline-step__icon">🔬</div>
      <div class="pipeline-step__label">Research</div>
    </div>
    <div class="pipeline-arrow">—</div>
    <div class="pipeline-step" data-step="draft">
      <div class="pipeline-step__icon">✍️</div>
      <div class="pipeline-step__label">Draft</div>
    </div>
    <div class="pipeline-arrow">—</div>
    <div class="pipeline-step" data-step="review">
      <div class="pipeline-step__icon">🔍</div>
      <div class="pipeline-step__label">Review</div>
    </div>
    <div class="pipeline-arrow">—</div>
    <div class="pipeline-step" data-step="approve">
      <div class="pipeline-step__icon">✅</div>
      <div class="pipeline-step__label">Approve</div>
    </div>
  </div>

  <!-- 최근 초안 -->
  <div class="section-card">
    <div class="section-card__header">RECENT DRAFTS</div>
    <div id="recentDrafts"><div class="feed-empty">— 없음 —</div></div>
  </div>
</div>
```

---

## STEP 8: Ops 탭 — 모니터링 덱

```html
<!-- OPS TAB INNER HTML -->
<div class="ops-page">
  <div class="page-header">
    <h2 class="page-header__title">운영 현황</h2>
    <span class="page-header__sub">큐 · 모니터 · 활동</span>
  </div>

  <!-- 큐 (가장 중요, 상단) -->
  <div class="ops-priority-card">
    <div class="ops-priority-card__header">
      <span>QUEUE</span>
      <span class="ops-badge" id="queueCount">0 pending</span>
    </div>
    <div id="queueItems"><div class="feed-empty">— 큐 비어 있음 —</div></div>
  </div>

  <!-- 모니터 그리드 (2열) -->
  <div class="ops-grid">
    <div class="ops-monitor-card">
      <div class="ops-monitor-card__title">REPLY MONITOR</div>
      <div class="ops-monitor-card__row">
        <span>상태</span>
        <span class="ops-active-badge" id="replyStatus">▶ 활성</span>
      </div>
      <div class="ops-monitor-card__row">
        <span>대기 중</span>
        <span id="replyPending">0</span>
      </div>
    </div>
    <div class="ops-monitor-card">
      <div class="ops-monitor-card__title">NEWS MONITOR</div>
      <div class="ops-monitor-card__row">
        <span>대기 기사</span>
        <span id="newsPending">0</span>
      </div>
      <div class="ops-monitor-card__row">
        <span>야간 버퍼</span>
        <span id="nightBuffer">0</span>
      </div>
    </div>
  </div>

  <!-- 활동 로그 -->
  <div class="section-card">
    <div class="section-card__header">ACTIVITY</div>
    <div id="activityLog"><div class="feed-empty">— 없음 —</div></div>
  </div>
</div>
```

---

## STEP 9: 구현 순서 (Claude Code 실행 순서)

```
1. 현재 대시보드 HTML 파일 경로 찾기
2. 기존 파일 → .backup 복사
3. dashboard.css 새로 생성 (STEP 1 + STEP 5 CSS 전체)
4. dashboard.js 새로 생성 (STEP 6 JS)
5. 메인 HTML 파일을 STEP 2 뼈대로 교체
6. 각 탭 내용 채우기 (STEP 3, 4, 7, 8)
7. 캐릭터 이미지 경로 실제 경로로 수정
8. 브라우저에서 열어서 확인
9. 확인 후 보고서 출력
```

---

## 하드 실패 기준 (자체 검증)

코드 완성 후 스스로 체크:
- [ ] Home이 스택된 카드처럼 보이는가? → FAIL
- [ ] AI 탭이 초상화+텍스트 행처럼 보이는가? → FAIL  
- [ ] 캐릭터가 정적으로 붙어있는가? → FAIL
- [ ] 파일명 텍스트가 UI에 보이는가? → FAIL
- [ ] 애니메이션이 없는가? → FAIL
- [ ] 배경이 단색 다크인가? → FAIL (orb + grid 있어야 함)

---

## 완료 보고서 형식

```
### 대시보드 재설계 완료 보고서

삭제된 기존 구조:
- [기존에 있던 것 중 제거한 것]

Home 재건:
- [구현한 내용]

AI 탭 재건:
- [구현한 내용]

Intake 탭:
- [구현한 내용]

Ops 탭:
- [구현한 내용]

캐릭터 통합 방식:
- 이미지 경로: [실제 경로]
- 마스크/페이드 적용: YES/NO
- 애니메이션 적용: YES/NO

수동 확인 포인트:
1. 브라우저에서 [URL] 접속
2. AI 탭 → 캐릭터 float 확인
3. Home 탭 → 미니 워커 이동 확인
4. 탭 전환 확인
```
