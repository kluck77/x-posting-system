// live2d.js — Live2D 캐릭터 대시보드 Hero 씬 통합
// 출처: pixi-live2d-display (guansss/CodePen 검증 패턴)

const _perf = {
  pageStart: performance.now(),
  live2dStart: null
};

async function initLive2D() {
  _perf.live2dStart = performance.now();
  const delayFromPageStart = (_perf.live2dStart - _perf.pageStart).toFixed(0);
  console.log(`[Live2D] 로드 시작 (페이지 로드 후 ${delayFromPageStart}ms)`);
  const heroScene = document.getElementById('heroScene');
  const canvas = document.getElementById('live2dCanvas');

  if (!canvas || !heroScene) return;

  // PIXI, Cubism이 로드될 때까지 대기 (최대 3초)
  let retries = 0;
  const maxRetries = 30; // 3초 (100ms × 30)
  while ((!window.PIXI || !window.Live2DCubismCore) && retries < maxRetries) {
    await new Promise(r => setTimeout(r, 100));
    retries++;
  }
  if (!window.PIXI || !window.Live2DCubismCore) {
    console.warn('Live2D: CDN 로드 지연. Hero 모델 스킵 — 대시보드는 정상 작동합니다.');
    return;
  }

  // PixiJS 앱 생성
  const app = new PIXI.Application({
    view: canvas,
    autoStart: true,
    resizeTo: heroScene,
    backgroundAlpha: 0,
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
    const scale = h / 2000;
    model.scale.set(scale);
    model.anchor.set(0.5, 1.0);
    model.x = app.screen.width * 0.5;
    model.y = app.screen.height * 1.02;
  }

  resizeModel();
  window.addEventListener('resize', resizeModel);

  // idle 모션 자동 시작 + 반복
  function playIdleLoop() {
    model.motion('idle').then(function() {
      playIdleLoop();
    }).catch(function() {
      setTimeout(playIdleLoop, 3000);
    });
  }
  playIdleLoop();

  // 시선 추적 (마우스/터치)
  document.addEventListener('pointermove', function(e) {
    model.focus(e.clientX, e.clientY);
  });
  document.addEventListener('touchmove', function(e) {
    var t = e.touches[0];
    model.focus(t.clientX, t.clientY);
  }, { passive: true });

  // 터치/클릭 반응
  canvas.style.pointerEvents = 'auto';
  model.on('hit', function(hitAreas) {
    if (hitAreas.includes('head')) {
      model.expression();
    }
    if (hitAreas.includes('body')) {
      model.motion('tap_body');
    }
  });

  // 터치 힌트 3초 후 제거
  setTimeout(function() {
    var hint = document.getElementById('tapHint');
    if (hint) {
      hint.style.opacity = '0';
      setTimeout(function() { hint.remove(); }, 600);
    }
  }, 3000);

  const elapsed = (_perf.live2dStart ? (performance.now() - _perf.live2dStart).toFixed(0) : '?');
  const totalPageTime = (performance.now() - _perf.pageStart).toFixed(0);
  console.log(`[Live2D] 초기화 완료 (로드 ${elapsed}ms, 총 ${totalPageTime}ms)`);
}

// Lazy load: 페이지 로드 후 2초 뒤 또는 사용자 상호작용 후 로드
function scheduleLive2DLoad() {
  // 이미 로드된 경우 스킵
  if (window._live2dScheduled) return;
  window._live2dScheduled = true;

  // 옵션 1: 2초 뒤 자동 로드 (페이지 로드 완료 후)
  setTimeout(() => {
    if (document.readyState === 'complete' || document.readyState === 'interactive') {
      initLive2D();
    }
  }, 2000);

  // 옵션 2: 사용자 상호작용 시 즉시 로드 (터치/클릭)
  const heroScene = document.getElementById('heroScene');
  if (heroScene) {
    heroScene.addEventListener('click', initLive2D, { once: true });
    heroScene.addEventListener('touchstart', initLive2D, { once: true });
  }
}

// DOM 준비되면 lazy load 스케줄링
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', scheduleLive2DLoad);
} else {
  scheduleLive2DLoad();
}
