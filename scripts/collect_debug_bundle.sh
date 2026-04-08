#!/usr/bin/env bash
# collect_debug_bundle.sh
# Usage: bash scripts/collect_debug_bundle.sh
# Collects a one-shot debug snapshot and writes it to a timestamped file.

SERVICE="xdashboard.service"
DB="x_poster.db"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BUNDLE="$PROJECT_ROOT/debug_${TIMESTAMP}.txt"

section() { printf '\n━━━ %s ━━━\n' "$1"; }
try()     { "$@" 2>/dev/null || echo "[FAILED] $*"; }

{

# ── 1. Timestamp ────────────────────────────────────────────
section "TIMESTAMP"
date -u '+%Y-%m-%d %H:%M:%S UTC'

# ── 2. Current working directory ────────────────────────────
section "PWD"
echo "$PROJECT_ROOT"

# ── 3. Git branch ───────────────────────────────────────────
section "GIT BRANCH"
try git branch --show-current

# ── 4. Git commit ───────────────────────────────────────────
section "GIT COMMIT"
try git rev-parse HEAD

# ── 5. Git status --short ───────────────────────────────────
section "GIT STATUS"
try git status --short

# ── 6. Service status summary ───────────────────────────────
section "SERVICE STATUS: $SERVICE"
try systemctl status "$SERVICE" --no-pager -l

# ── 7. Last 100 journal lines ───────────────────────────────
section "JOURNAL LOG (last 100 lines)"
try journalctl -u "$SERVICE" -n 100 --no-pager

# ── 8. Error / Exception / traceback lines (last 24h) ───────
section "ERROR / EXCEPTION LINES (last 24h)"
journalctl -u "$SERVICE" --since "24h ago" --no-pager 2>/dev/null \
  | grep -iE "error|exception|traceback|raise |criteria_context|fallback|실패" \
  || echo "(none found)"

# ── 9. Running Python process check ─────────────────────────
section "RUNNING PYTHON PROCESS"
pgrep -a -f "python\|uvicorn\|gunicorn\|run\.py" 2>/dev/null \
  || echo "(no matching python process found)"

# ── 10. Env var presence check (no values printed) ──────────
section "ENV VAR PRESENCE"
for var in \
  OPENAI_API_KEY \
  ANTHROPIC_API_KEY \
  TELEGRAM_BOT_TOKEN \
  TELEGRAM_CHAT_ID \
  X_API_KEY; do
  if systemctl show "$SERVICE" --property=Environment 2>/dev/null \
      | grep -q "${var}="; then
    echo "  ${var}: OK"
  elif printenv "$var" &>/dev/null; then
    echo "  ${var}: OK (shell env)"
  else
    echo "  ${var}: MISSING"
  fi
done

# ── 11. Recent drafts from SQLite ───────────────────────────
section "RECENT DRAFTS (SQLite)"
if ! command -v sqlite3 &>/dev/null; then
  echo "(sqlite3 not installed — skipped)"
elif [ ! -f "$PROJECT_ROOT/$DB" ]; then
  echo "(DB not found: $PROJECT_ROOT/$DB)"
else
  sqlite3 "$PROJECT_ROOT/$DB" \
    "SELECT id, substr(hook,1,60), risk_level, approval_status, created_at
     FROM drafts ORDER BY id DESC LIMIT 10;" \
    2>/dev/null || echo "[FAILED] sqlite3 query"
fi

# ── 12. Output file path ─────────────────────────────────────
section "BUNDLE OUTPUT"
echo "$BUNDLE"

} > "$BUNDLE" 2>&1

echo ""
echo "✓ Debug bundle saved:"
echo "  $BUNDLE"
echo ""
echo "Paste the contents into chat:"
echo "  cat $BUNDLE"
