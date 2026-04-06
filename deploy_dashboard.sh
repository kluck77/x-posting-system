#!/bin/bash
# ─────────────────────────────────────────────────────────────
# X Posting System — 대시보드 배포 스크립트
# 서버에서 직접 실행: bash deploy_dashboard.sh
# ─────────────────────────────────────────────────────────────
set -e

REPO_URL="https://github.com/kluck77/x-posting-system.git"
BRANCH="claude/extract-prediction-time-n82UK"
APP_DIR="/root/x-posting-system"
SERVICE_NAME="xdashboard"
PORT=8000

echo "=== X Control Room 배포 시작 ==="

# 1. Python 확인
echo "[1/6] Python 확인..."
python3 --version || { echo "python3 없음. apt install python3 python3-pip -y"; exit 1; }

# 2. 코드 받기
echo "[2/6] 코드 pull..."
if [ -d "$APP_DIR" ]; then
    cd "$APP_DIR"
    git fetch origin
    git checkout "$BRANCH"
    git pull origin "$BRANCH"
else
    git clone -b "$BRANCH" "$REPO_URL" "$APP_DIR"
    cd "$APP_DIR"
fi

# 3. 가상환경 + 패키지
echo "[3/6] 패키지 설치..."
python3 -m venv .venv 2>/dev/null || true
source .venv/bin/activate
pip install -q --upgrade pip
pip install -q fastapi uvicorn sqlalchemy python-dotenv pydantic-settings aiofiles

# 4. .env 확인
echo "[4/6] .env 확인..."
if [ ! -f ".env" ]; then
    echo "⚠️  .env 파일 없음 — 최소한의 .env 생성 (mock 모드)"
    cat > .env << 'EOF'
# 대시보드 전용 최소 설정
MOCK_MODE=true
TELEGRAM_BOT_TOKEN=dummy
TELEGRAM_CHAT_ID=0
EOF
    echo "   → .env 생성됨 (mock 모드). 실제 키가 있으면 직접 편집하세요."
fi

# 5. systemd 서비스 등록
echo "[5/6] systemd 서비스 등록..."
cat > /etc/systemd/system/${SERVICE_NAME}.service << EOF
[Unit]
Description=X Posting Control Room Dashboard
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=${APP_DIR}
ExecStart=${APP_DIR}/.venv/bin/uvicorn app.api.admin:app --host 0.0.0.0 --port ${PORT}
Restart=always
RestartSec=5
Environment=PYTHONPATH=${APP_DIR}

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable "$SERVICE_NAME"
systemctl restart "$SERVICE_NAME"

# 6. 방화벽 열기 (ufw 있을 경우)
echo "[6/6] 방화벽 설정..."
if command -v ufw &> /dev/null; then
    ufw allow ${PORT}/tcp 2>/dev/null || true
    echo "   → ufw: 포트 ${PORT} 허용"
fi

# 결과 확인
sleep 3
if systemctl is-active --quiet "$SERVICE_NAME"; then
    echo ""
    echo "✅ 배포 완료!"
    echo "   대시보드: http://$(curl -s ifconfig.me 2>/dev/null || echo '서버IP'):${PORT}/control/"
    echo "   서비스: systemctl status ${SERVICE_NAME}"
    echo "   로그:   journalctl -u ${SERVICE_NAME} -f"
else
    echo "❌ 서비스 시작 실패. 로그 확인:"
    journalctl -u "$SERVICE_NAME" --no-pager -n 30
fi
