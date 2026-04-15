#!/bin/bash
# x-posting-system 배포 스크립트
# =================================
# 사용법:
#   bash scripts/deploy.sh                       # 기본 브랜치 배포
#   bash scripts/deploy.sh main                  # main 브랜치 배포
#   bash scripts/deploy.sh claude/feature-xyz    # 임의 브랜치 배포
#
# 자동 수행:
#   1) xdashboard.service 부활 감지 → 즉시 disable
#      (같은 봇 토큰을 중복 polling → Telegram Conflict 방지)
#   2) git pull (지정 브랜치)
#   3) systemctl restart x-posting-bot
#   4) 5초 대기 후 서비스 상태 확인
#   5) 30초 동안 Conflict 에러 감시 → 0 이면 성공, 그 외 즉시 실패
#
# 실패 처리:
#   - Conflict 가 30초 안에 1회라도 뜨면 exit 1
#   - 이 경우 다른 머신 또는 수동 프로세스가 같은 봇 토큰으로
#     polling 중일 가능성. pgrep -af python.*run\.py 로 추적.

set -e

REPO_DIR="/root/x-posting-system"
DEFAULT_BRANCH="claude/fix-operatorhints-error-UryDJ"
BRANCH="${1:-$DEFAULT_BRANCH}"
SERVICE="x-posting-bot"

cd "$REPO_DIR"

echo "=== [1/5] xdashboard 부활 체크 ==="
if systemctl is-enabled xdashboard.service 2>/dev/null | grep -q enabled; then
    echo "⚠️  xdashboard 다시 활성화됨 → 즉시 disable"
    systemctl disable --now xdashboard.service
else
    echo "OK (disabled 또는 미존재)"
fi
echo ""

echo "=== [2/5] git pull ($BRANCH) ==="
git pull origin "$BRANCH"
echo ""

echo "=== [3/5] 서비스 재시작 ==="
systemctl restart "$SERVICE"
sleep 5
echo ""

echo "=== [4/5] 서비스 상태 ==="
systemctl status "$SERVICE" --no-pager | head -8
echo ""

echo "=== [5/5] 30초 Conflict 관찰 ==="
sleep 30
CONFLICT_COUNT=$(journalctl -u "$SERVICE" --since "35 sec ago" --no-pager | grep -c "Conflict:")
echo "Conflict 카운트: $CONFLICT_COUNT"

if [ "$CONFLICT_COUNT" -eq 0 ]; then
    echo ""
    echo "✅ 배포 성공"
    exit 0
else
    echo ""
    echo "🚨 Conflict 발생 — 다른 봇 인스턴스 추적 필요"
    echo "    pgrep -af 'python.*run\\.py' 로 이 서버 프로세스 확인"
    echo "    ss -tnp | grep 149.154 로 Telegram API 연결 확인"
    echo "    계속되면 BotFather /revoke 로 토큰 재발급"
    exit 1
fi
