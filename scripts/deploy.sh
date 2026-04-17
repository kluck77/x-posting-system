#!/bin/bash
# x-posting-system 배포 스크립트
# =================================
# 사용법:
#   bash scripts/deploy.sh                       # 기본 브랜치 배포
#   bash scripts/deploy.sh main                  # main 브랜치 배포
#   bash scripts/deploy.sh claude/feature-xyz    # 임의 브랜치 배포
#
# 자동 수행:
#   0) xdashboard.service 부활 감지 → 즉시 disable
#   1) systemd 관리 밖 수동 run.py 프로세스 kill
#      (누가 python run.py 를 손으로 띄워놨을 때 자동 청소)
#   2) git pull (지정 브랜치)
#   3) systemctl restart x-posting-bot
#   4) 5초 대기 후 서비스 상태 확인
#   5) 30초 동안 Conflict 에러 감시 → 0 이면 성공, 그 외 즉시 실패
#
# 실패 처리:
#   - Conflict 가 30초 안에 1회라도 뜨면 exit 1
#   - 이 경우 다른 머신(로컬 노트북, 다른 서버)이 같은 봇 토큰으로
#     polling 중일 가능성. BotFather /revoke 로 토큰 재발급 필요.

set -e

REPO_DIR="/root/x-posting-system"
DEFAULT_BRANCH="claude/fix-operatorhints-error-UryDJ"
BRANCH="${1:-$DEFAULT_BRANCH}"
SERVICE="x-posting-bot"

cd "$REPO_DIR"

echo "=== [0/6] xdashboard 부활 체크 ==="
if systemctl is-enabled xdashboard.service 2>/dev/null | grep -q enabled; then
    echo "⚠️  xdashboard 다시 활성화됨 → 즉시 disable"
    systemctl disable --now xdashboard.service
else
    echo "OK (disabled 또는 미존재)"
fi
echo ""

echo "=== [1/6] systemd 밖 수동 run.py 정리 ==="
# systemd 가 관리하는 MainPID 외의 모든 python run.py 프로세스를 kill
# (누가 서버 들어와서 python run.py 손으로 띄워둔 상황 자동 청소)
MAIN_PID=$(systemctl show "$SERVICE" -p MainPID --value 2>/dev/null || echo 0)
ROGUE=$(pgrep -f "python.*run\.py" 2>/dev/null | grep -v "^${MAIN_PID}$" || true)
if [ -n "$ROGUE" ]; then
    echo "⚠️  systemd 밖 수동 프로세스 감지 → kill:"
    echo "$ROGUE" | while read -r pid; do
        ps -o pid,lstart,cmd -p "$pid" 2>/dev/null || true
    done
    echo "$ROGUE" | xargs -r kill 2>/dev/null || true
    sleep 2
    # 여전히 살아있으면 -9
    STILL=$(pgrep -f "python.*run\.py" 2>/dev/null | grep -v "^${MAIN_PID}$" || true)
    if [ -n "$STILL" ]; then
        echo "   → SIGTERM 무시됨, SIGKILL 로 강제 종료"
        echo "$STILL" | xargs -r kill -9 2>/dev/null || true
        sleep 1
    fi
    echo "   정리 완료"
else
    echo "OK (systemd MainPID=$MAIN_PID 외 수동 프로세스 없음)"
fi
echo ""

echo "=== [2/6] git pull ($BRANCH) ==="
git pull origin "$BRANCH"
echo ""

echo "=== [3/6] 서비스 재시작 ==="
systemctl restart "$SERVICE"
sleep 5
echo ""

echo "=== [4/6] 서비스 상태 ==="
systemctl status "$SERVICE" --no-pager | head -8
echo ""

echo "=== [5/6] 30초 Conflict 관찰 ==="
sleep 30
# grep -c 는 매치 0 일 때 exit 1 을 반환하므로 set -e 하에서 죽지 않도록 || true
CONFLICT_COUNT=$(journalctl -u "$SERVICE" --since "35 sec ago" --no-pager | grep -c "Conflict:" || true)
echo "Conflict 카운트: $CONFLICT_COUNT"
echo ""

echo "=== [6/6] 최종 판정 ==="
if [ "$CONFLICT_COUNT" -eq 0 ]; then
    echo "✅ 배포 성공"
    exit 0
else
    echo "🚨 Conflict 발생 — 다른 봇 인스턴스 추적 필요"
    echo "    이 서버 내부는 [1/6] 에서 정리됨 → 외부 머신 가능성"
    echo "    → BotFather /revoke 로 토큰 재발급 후 .env 갱신 + 재배포"
    exit 1
fi
