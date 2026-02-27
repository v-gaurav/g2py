#!/bin/bash
set -euo pipefail

# 05-sync-groups.sh — Connect to WhatsApp, fetch group metadata, write to DB, exit.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
LOG_FILE="$PROJECT_ROOT/logs/setup.log"

mkdir -p "$PROJECT_ROOT/logs"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] [sync-groups] $*" >> "$LOG_FILE"; }

cd "$PROJECT_ROOT"

# Run group sync via the Python app
log "Fetching group metadata"
SYNC="failed"

SYNC_OUTPUT=$(uv run python -m g2 sync-groups 2>&1) || true

log "Sync output: $SYNC_OUTPUT"

if echo "$SYNC_OUTPUT" | grep -q "SYNCED:"; then
  SYNC="success"
fi

# Check for groups in DB
GROUPS_IN_DB=0
if [ -f "$PROJECT_ROOT/store/messages.db" ]; then
  GROUPS_IN_DB=$(sqlite3 "$PROJECT_ROOT/store/messages.db" "SELECT COUNT(*) FROM chats WHERE jid LIKE '%@g.us' AND jid <> '__group_sync__'" 2>/dev/null || echo "0")
  log "Groups found in DB: $GROUPS_IN_DB"
fi

STATUS="success"
if [ "$SYNC" != "success" ]; then
  STATUS="failed"
fi

cat <<EOF
=== G2 SETUP: SYNC_GROUPS ===
SYNC: $SYNC
GROUPS_IN_DB: $GROUPS_IN_DB
STATUS: $STATUS
LOG: logs/setup.log
=== END ===
EOF

if [ "$STATUS" = "failed" ]; then
  exit 1
fi
