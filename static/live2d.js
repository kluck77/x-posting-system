// live2d.js — Live2D 캐릭터 대시보드 Hero 씬 통합
// 출처: pixi-live2d-display (guansss/CodePen 검증 패턴)

async function initLive2D() {
  const heroScene = document.getElementById('heroScene');
  const canvas = document.getElementById('live2dCanvas');

  if (!canvas || !heroScene) return;

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

  console.log('[Live2D] 초기화 완료 — shizuku 로드됨');
}

// DOM 준비 후 실행
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initLive2D);
} else {
  initLive2D();
}
