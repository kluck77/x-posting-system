#!/usr/bin/env bash
# collect_debug_bundle.sh
# One-command debug snapshot for x-posting-system.
# Run: bash scripts/collect_debug_bundle.sh
# Output: debug_YYYYMMDD_HHMMSS.txt in the project root

set -euo pipefail

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BUNDLE="debug_${TIMESTAMP}.txt"
SERVICE="xdashboard.service"
DB="x_poster.db"

# Resolve project root (script lives in scripts/)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

section() { echo; echo "━━━ $1 ━━━"; }
fail()    { echo "[FAILED] $1"; }

{
  echo "x-posting-system debug bundle"
  echo "Generated: $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
  echo "Host: $(hostname)"

  # ── 1. Git state ───────────────────────────────────────────
  section "GIT STATE"
  git branch --show-current          2>/dev/null || fail "git branch"
  git rev-parse --short HEAD         2>/dev/null || fail "git rev-parse"
  git status --short                 2>/dev/null || fail "git status"

  # ── 2. Service status ──────────────────────────────────────
  section "SERVICE STATUS"
  systemctl is-active "$SERVICE"     2>/dev/null || fail "systemctl is-active"
  systemctl show "$SERVICE" \
    --property=ActiveState,SubState,ExecMainPID,MainPID \
    2>/dev/null                                  || fail "systemctl show"

  # ── 3. Running process ─────────────────────────────────────
  section "RUNNING PROCESS"
  pgrep -a -f "run.py\|uvicorn\|gunicorn\|xdashboard" \
    2>/dev/null || echo "(no matching process found)"

  # ── 4. Last 100 log lines ──────────────────────────────────
  section "JOURNAL LOG (last 100 lines)"
  journalctl -u "$SERVICE" -n 100 --no-pager \
    2>/dev/null || fail "journalctl"

  # ── 5. Error / Exception lines (last 24 h) ─────────────────
  section "ERROR / EXCEPTION LINES (last 24h)"
  journalctl -u "$SERVICE" --since "24h ago" --no-pager \
    2>/dev/null \
    | grep -E "ERROR|Exception|Traceback|raise |criteria_context|fallback|실패" \
    || echo "(none found)"

  # ── 6. Environment variable presence (NO values) ───────────
  section "ENV VAR PRESENCE CHECK"
  for var in \
    OPENAI_API_KEY \
    ANTHROPIC_API_KEY \
    TELEGRAM_BOT_TOKEN \
    TELEGRAM_CHAT_ID \
    X_API_KEY \
    X_API_SECRET \
    X_ACCESS_TOKEN \
    X_ACCESS_TOKEN_SECRET \
    DATABASE_URL \
    ACTIVE_DRAFT_PROVIDER \
    DEFAULT_LANGUAGE; do
    if systemctl show "$SERVICE" --property=Environment 2>/dev/null \
        | grep -q "${var}="; then
      echo "  ${var}: OK"
    elif printenv "$var" &>/dev/null; then
      echo "  ${var}: OK (shell env)"
    else
      echo "  ${var}: MISSING"
    fi
  done

  # ── 7. Recent drafts from SQLite ───────────────────────────
  section "RECENT DRAFTS (SQLite)"
  if command -v sqlite3 &>/dev/null && [ -f "$DB" ]; then
    sqlite3 "$DB" \
      "SELECT id, substr(hook,1,60), risk_level, approval_status,
              created_at
       FROM drafts
       ORDER BY id DESC
       LIMIT 10;" \
      2>/dev/null || fail "sqlite3 query"
  elif [ ! -f "$DB" ]; then
    echo "(DB not found at $PROJECT_ROOT/$DB)"
  else
    echo "(sqlite3 not installed — skipped)"
  fi

  # ── 8. Disk space (sanity check) ───────────────────────────
  section "DISK SPACE"
  df -h "$PROJECT_ROOT" 2>/dev/null || fail "df"

} > "$BUNDLE" 2>&1

echo ""
echo "✓ Debug bundle saved: $PROJECT_ROOT/$BUNDLE"
echo "  Share this file or paste its contents into chat."
