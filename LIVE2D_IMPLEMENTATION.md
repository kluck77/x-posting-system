# LIVE2D_IMPLEMENTATION.md
# 실제 디자이너/개발자가 쓰는 방법으로 Live2D 캐릭터 대시보드 구현
# 리서치 출처: CodePen(guansss), GitHub(evrstr, Konata09, guansss/pixi-live2d-display)
# Claude Code 작업 지시서

---

## 핵심 발견 (리서치 결과)

실제 웹 개발자들이 쓰는 방법은 두 가지다:

### 방법 A — pixi-live2d-display (권장, 고퀄리티)
- PixiJS 기반, WebGL 렌더링
- 실제 뼈대 애니메이션: 눈깜빡임, 호흡, 머리 추적, 터치 반응
- CDN 4줄로 바로 시작 가능
- 무료 모델 100개+ CDN으로 바로 로드 가능
- 출처: https://codepen.io/guansss/pen/oNzoNoz

### 방법 B — live2d-widget (더 간단)
- 한 줄 init으로 캐릭터 추가
- 하지만 위치 커스터마이즈 제한적

**→ 방법 A로 구현. 대시보드 Hero 씬에 완전 통합 가능.**

---

## 실제 작동이 검증된 CDN URL (CodePen에서 확인됨)

```html
<!-- 1. Cubism Core (Live2D 엔진) -->
<script src="https://cubism.live2d.com/sdk-web/cubismcore/live2dcubismcore.min.js"></script>

<!-- 2. Cubism 2.1 런타임 -->
<script src="https://cdn.jsdelivr.net/gh/dylanNew/live2d/webgl/Live2D/lib/live2d.min.js"></script>

<!-- 3. PixiJS 6 -->
<script src="https://cdn.jsdelivr.net/npm/pixi.js@6.5.2/dist/browser/pixi.min.js"></script>

<!-- 4. pixi-live2d-display (Cubism 2+4 통합) -->
<script src="https://cdn.jsdelivr.net/npm/pixi-live2d-display/dist/index.min.js"></script>
```

---

## 실제 작동이 검증된 무료 모델 URL

CodePen 원작자(guansss)의 테스트 에셋 — 공식 라이선스 모델:

```
# shizuku (금발 여성, 헤드폰, 파란 눈 — 비서 느낌에 가장 적합)
https://cdn.jsdelivr.net/gh/guansss/pixi-live2d-display/test/assets/shizuku/shizuku.model.json

# haru (갈색 머리 여성, 인사 모션)
https://cdn.jsdelivr.net/gh/guansss/pixi-live2d-display/test/assets/haru/haru_greeter_t03.model3.json
```

evrstr 컬렉션 (100개+):
```
# koharu — 귀여운 캐릭터
https://cdn.jsdelivr.net/gh/evrstr/live2d-widget-models/live2d_evrstr/koharu/model.json

# natori — 오피스 느낌
https://cdn.jsdelivr.net/gh/evrstr/live2d-widget-models/live2d_evrstr/natori/model.json

# izumi
https://cdn.jsdelivr.net/gh/evrstr/live2d-widget-models/live2d_evrstr/izumi/model.json

# histoire — 비서 스타일
https://cdn.jsdelivr.net/gh/evrstr/live2d-widget-models/live2d_evrstr/histoire/model.json
```

---

## 구현 구조 (검증된 패턴)

```javascript
// CodePen 원작자 코드 그대로 — 실제 작동 확인됨
(async function() {
  const app = new PIXI.Application({
    view: document.getElementById('live2dCanvas'),
    autoStart: true,
    transparent: true,   // 배경 투명 — 대시보드 씬에 녹아들게
    backgroundColor: 0x000000,
    backgroundAlpha: 0,
  });

  // 모델 로드
  const model = await PIXI.live2d.Live2DModel.from(
    'https://cdn.jsdelivr.net/gh/guansss/pixi-live2d-display/test/assets/shizuku/shizuku.model.json'
  );

  app.stage.addChild(model);

  // 크기/위치 설정
  model.scale.set(0.25);
  model.anchor.set(0.5, 1.0);    // 발 기준 앵커
  model.x = app.screen.width / 2;
  model.y = app.screen.height;

  // 자동 idle 모션 시작
  model.motion('idle');

  // 터치/클릭 반응
  model.on('hit', (hitAreas) => {
    if (hitAreas.includes('head')) {
      model.expression();       // 랜덤 표정
    }
    if (hitAreas.includes('body')) {
      model.motion('tap_body'); // 터치 반응 모션
    }
  });

  // 마우스/터치로 시선 추적
  document.addEventListener('pointermove', (e) => {
    model.focus(e.clientX, e.clientY);
  });

})();
```

---

## STEP 0: 작업 전 준비

```bash
# 현재 대시보드 HTML 파일 경로 확인
# 기존 파일 백업
cp dashboard.html dashboard.html.backup
```

---

## STEP 1: 기존 홈 탭 Hero 씬 재구성

### 교체 목표
- 기존: 정적 이미지가 좌우 이동
- 목표: Live2D 캐릭터가 실제로 숨쉬고, 눈 깜빡이고, 시선이 따라오고, 터치하면 반응

### HTML 구조

```html
<!-- 기존 hero-scene 내부를 이렇게 교체 -->
<div class="hero-scene" id="heroScene">

  <!-- Live2D 캔버스 — 씬 전체를 채움 -->
  <canvas id="live2dCanvas" style="
    position: absolute;
    bottom: 0;
    left: 0;
    width: 100%;
    height: 100%;
    pointer-events: none;
  "></canvas>

  <!-- 기존 글래스 패널들은 그대로 유지 (z-index로 위에 표시) -->
  <div class="gpanel gpanel-tl" style="z-index:10; position:relative;">
    ...시스템 상태 패널...
  </div>
  <div class="gpanel gpanel-tr" style="z-index:10; position:relative;">
    ...할당량 패널...
  </div>

  <!-- 씬 하단 제목 -->
  <div class="hero-title" style="z-index:10; position:relative;">
    <div class="ht-sub">AI Content Operations</div>
    <div class="ht-main">Control Room</div>
  </div>

  <!-- 터치 힌트 — 처음 3초 후 사라짐 -->
  <div class="tap-hint" id="tapHint">
    캐릭터를 터치해보세요 ✨
  </div>
</div>
```

### Live2D 초기화 JS (dashboard.js 또는 별도 live2d.js)

```javascript
// live2d.js — 이 파일을 새로 생성

async function initLive2D() {
  const heroScene = document.getElementById('heroScene');
  const canvas = document.getElementById('live2dCanvas');

  if (!canvas || !heroScene) return;

  // PixiJS 앱 생성
  const app = new PIXI.Application({
    view: canvas,
    autoStart: true,
    resizeTo: heroScene,       // hero-scene 크기에 맞춤
    backgroundAlpha: 0,        // 완전 투명 배경
  });

  // Live2D 모델 로드
  // shizuku: 금발, 헤드폰, 비서 느낌 — idle 모션 3종, 터치 반응 있음
  const MODEL_URL =
    'https://cdn.jsdelivr.net/gh/guansss/pixi-live2d-display/test/assets/shizuku/shizuku.model.json';

  let model;
  try {
    model = await PIXI.live2d.Live2DModel.from(MODEL_URL);
  } catch(e) {
    console.warn('Live2D 로드 실패:', e);
    return; // 실패해도 대시보드는 정상 작동
  }

  app.stage.addChild(model);

  // 모델 위치/크기 설정
  function resizeModel() {
    const h = heroScene.offsetHeight;
    const scale = h / 2000; // 모델 높이 기준 스케일
    model.scale.set(scale);
    model.anchor.set(0.5, 1.0);
    model.x = app.screen.width * 0.5;   // 가운데 배치
    model.y = app.screen.height * 1.02; // 살짝 잘리게 (자연스러움)
  }

  resizeModel();
  window.addEventListener('resize', resizeModel);

  // idle 모션 자동 시작 + 반복
  function playIdleLoop() {
    model.motion('idle').then(() => {
      playIdleLoop(); // 끝나면 다시 시작
    }).catch(() => {
      setTimeout(playIdleLoop, 3000);
    });
  }
  playIdleLoop();

  // 시선 추적 (마우스/터치)
  document.addEventListener('pointermove', (e) => {
    model.focus(e.clientX, e.clientY);
  });
  document.addEventListener('touchmove', (e) => {
    const t = e.touches[0];
    model.focus(t.clientX, t.clientY);
  }, { passive: true });

  // 터치/클릭 반응
  canvas.style.pointerEvents = 'auto'; // 캔버스 클릭 활성화
  model.on('hit', (hitAreas) => {
    if (hitAreas.includes('head')) {
      model.expression();         // 표정 변화
    }
    if (hitAreas.includes('body')) {
      model.motion('tap_body');   // 반응 모션
    }
  });

  // 터치 힌트 3초 후 제거
  setTimeout(() => {
    const hint = document.getElementById('tapHint');
    if (hint) {
      hint.style.opacity = '0';
      setTimeout(() => hint.remove(), 600);
    }
  }, 3000);

  console.log('[Live2D] 초기화 완료 — shizuku 로드됨');
}

// DOM 준비 후 실행
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initLive2D);
} else {
  initLive2D();
}
```

---

## STEP 2: HTML head에 스크립트 추가

```html
<!-- 기존 스크립트들 위에 추가 -->
<script src="https://cubism.live2d.com/sdk-web/cubismcore/live2dcubismcore.min.js"></script>
<script src="https://cdn.jsdelivr.net/gh/dylanNew/live2d/webgl/Live2D/lib/live2d.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/pixi.js@6.5.2/dist/browser/pixi.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/pixi-live2d-display/dist/index.min.js"></script>

<!-- 기존 스크립트들 -->
<script src="dashboard.js"></script>

<!-- Live2D 초기화 (가장 마지막에) -->
<script src="live2d.js"></script>
```

---

## STEP 3: Hero 씬 CSS 조정

```css
/* hero-scene: Live2D가 제대로 보이게 */
.hero-scene {
  position: relative;
  overflow: hidden;
  /* 높이는 기존 값 유지 */
}

/* Live2D 캔버스 */
#live2dCanvas {
  position: absolute;
  bottom: 0;
  left: 0;
  width: 100%;
  height: 100%;
  /* 캐릭터가 씬 배경에 자연스럽게 녹아들게 */
  /* Live2D 자체가 투명 배경이라 별도 처리 불필요 */
}

/* 터치 힌트 */
.tap-hint {
  position: absolute;
  bottom: 60px;
  left: 50%;
  transform: translateX(-50%);
  font-size: 11px;
  color: rgba(165, 180, 252, 0.7);
  font-family: var(--mono);
  pointer-events: none;
  z-index: 15;
  transition: opacity 0.6s ease;
  white-space: nowrap;
}
```

---

## STEP 4: AI 탭 — 각 캐릭터 스테이션 유지

AI 탭의 각 캐릭터(DraftWriter, Researcher 등)는:
- 기존 이미지 그대로 유지 (Live2D 모델 없음)
- CSS 애니메이션 (charType, charScan, charNod) 그대로 유지
- 추후 개별 Live2D 모델로 교체 가능

**지금은 홈 탭 Hero에만 Live2D 집중.**

---

## STEP 5: 검증 체크리스트

구현 후 반드시 확인:

```
[ ] 브라우저 콘솔에 '[Live2D] 초기화 완료' 출력되는가?
[ ] 캐릭터가 Hero 씬 안에 표시되는가?
[ ] 캐릭터가 idle 모션으로 숨쉬고 있는가? (가만히 있어도 미세하게 움직임)
[ ] 눈을 깜빡이는가?
[ ] 마우스/손가락 움직이면 시선이 따라오는가?
[ ] 캐릭터 몸 터치 시 모션이 실행되는가?
[ ] 기존 대시보드 기능(탭 전환, API 연결 등)이 그대로 작동하는가?
[ ] 모바일 Safari에서 렌더링되는가?
[ ] Live2D 로드 실패해도 대시보드는 정상 작동하는가?
```

---

## 완료 보고서 형식

```
### Live2D 구현 완료 보고서

Live2D 라이브러리 로드: 성공/실패
모델 URL: [사용한 URL]
캐릭터 표시: YES/NO
idle 모션: YES/NO
시선 추적: YES/NO
터치 반응: YES/NO
모바일 확인: YES/NO
기존 기능 영향: 없음/있음(내용)
콘솔 에러: 없음/있음(내용)
```

---

## 트러블슈팅

### 모델이 안 뜨는 경우
→ CDN 차단 가능성. 다음 대체 URL 시도:
```
https://cdn.jsdelivr.net/gh/evrstr/live2d-widget-models/live2d_evrstr/koharu/model.json
```

### 캔버스가 빈 경우
→ `backgroundAlpha: 0` 옵션 확인. PixiJS 버전 6.5.2 정확히 사용했는지 확인.

### 모바일에서 안 보이는 경우
→ WebGL 지원 확인. `app.renderer.type === PIXI.RENDERER_TYPE.WEBGL` 체크.

### CORS 에러
→ CDN URL은 CORS 허용됨. 로컬 파일(file://) 프로토콜에서는 에러 날 수 있음.
   VPS의 실제 도메인/IP에서 실행할 것.
