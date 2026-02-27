#!/bin/bash
set -euo pipefail

# 06-register-channel.sh — Write channel registration config, create group folders

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
LOG_FILE="$PROJECT_ROOT/logs/setup.log"

mkdir -p "$PROJECT_ROOT/logs"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] [register-channel] $*" >> "$LOG_FILE"; }

cd "$PROJECT_ROOT"

# Parse args
JID=""
NAME=""
TRIGGER=""
FOLDER=""
REQUIRES_TRIGGER="true"
ASSISTANT_NAME="G2"

while [[ $# -gt 0 ]]; do
  case $1 in
    --jid)              JID="$2"; shift 2 ;;
    --name)             NAME="$2"; shift 2 ;;
    --trigger)          TRIGGER="$2"; shift 2 ;;
    --folder)           FOLDER="$2"; shift 2 ;;
    --no-trigger-required) REQUIRES_TRIGGER="false"; shift ;;
    --assistant-name)   ASSISTANT_NAME="$2"; shift 2 ;;
    *) shift ;;
  esac
done

# Validate required args
if [ -z "$JID" ] || [ -z "$NAME" ] || [ -z "$TRIGGER" ] || [ -z "$FOLDER" ]; then
  log "ERROR: Missing required args (--jid, --name, --trigger, --folder)"
  cat <<EOF
=== G2 SETUP: REGISTER_CHANNEL ===
STATUS: failed
ERROR: missing_required_args
LOG: logs/setup.log
=== END ===
EOF
  exit 4
fi

log "Registering channel: jid=$JID name=$NAME trigger=$TRIGGER folder=$FOLDER requiresTrigger=$REQUIRES_TRIGGER"

# Create data directory and store directory
mkdir -p "$PROJECT_ROOT/data" "$PROJECT_ROOT/store"

# Write directly to SQLite
TIMESTAMP=$(date -u '+%Y-%m-%dT%H:%M:%S.000Z')
REQUIRES_TRIGGER_INT=$( [ "$REQUIRES_TRIGGER" = "true" ] && echo 1 || echo 0 )

sqlite3 "$PROJECT_ROOT/store/messages.db" <<SQLEOF
CREATE TABLE IF NOT EXISTS registered_groups (
  jid TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  folder TEXT NOT NULL UNIQUE,
  trigger_pattern TEXT NOT NULL,
  added_at TEXT NOT NULL,
  container_config TEXT,
  requires_trigger INTEGER DEFAULT 1,
  channel TEXT DEFAULT 'whatsapp'
);

INSERT OR REPLACE INTO registered_groups (jid, name, folder, trigger_pattern, added_at, container_config, requires_trigger, channel)
VALUES ('$JID', '$NAME', '$FOLDER', '$TRIGGER', '$TIMESTAMP', NULL, $REQUIRES_TRIGGER_INT, 'whatsapp');
SQLEOF

log "Wrote registration to SQLite"

# Verify
REGISTERED=$(sqlite3 "$PROJECT_ROOT/store/messages.db" "SELECT jid, name, folder FROM registered_groups WHERE jid = '$JID'" 2>/dev/null || echo "")
log "Registered: $REGISTERED"

# Create group folders
mkdir -p "$PROJECT_ROOT/groups/$FOLDER/logs"
log "Created groups/$FOLDER/logs/"

# Update assistant name in CLAUDE.md files if different from default
NAME_UPDATED="false"
if [ "$ASSISTANT_NAME" != "G2" ]; then
  log "Updating assistant name from G2 to $ASSISTANT_NAME"

  for md_file in groups/global/CLAUDE.md groups/main/CLAUDE.md; do
    if [ -f "$PROJECT_ROOT/$md_file" ]; then
      if sed --version >/dev/null 2>&1; then
        # GNU sed (Linux)
        sed -i "s/^# G2$/# $ASSISTANT_NAME/" "$PROJECT_ROOT/$md_file"
        sed -i "s/You are G2/You are $ASSISTANT_NAME/g" "$PROJECT_ROOT/$md_file"
      else
        # BSD sed (macOS)
        sed -i '' "s/^# G2$/# $ASSISTANT_NAME/" "$PROJECT_ROOT/$md_file"
        sed -i '' "s/You are G2/You are $ASSISTANT_NAME/g" "$PROJECT_ROOT/$md_file"
      fi
      log "Updated $md_file"
    else
      log "WARNING: $md_file not found, skipping name update"
    fi
  done

  # Add ASSISTANT_NAME to .env so config picks it up
  ENV_FILE="$PROJECT_ROOT/.env"
  if [ -f "$ENV_FILE" ] && grep -q '^ASSISTANT_NAME=' "$ENV_FILE"; then
    if sed --version >/dev/null 2>&1; then
      sed -i "s|^ASSISTANT_NAME=.*|ASSISTANT_NAME=\"$ASSISTANT_NAME\"|" "$ENV_FILE"
    else
      sed -i '' "s|^ASSISTANT_NAME=.*|ASSISTANT_NAME=\"$ASSISTANT_NAME\"|" "$ENV_FILE"
    fi
  else
    echo "ASSISTANT_NAME=\"$ASSISTANT_NAME\"" >> "$ENV_FILE"
  fi
  log "Set ASSISTANT_NAME=$ASSISTANT_NAME in .env"

  NAME_UPDATED="true"
fi

cat <<EOF
=== G2 SETUP: REGISTER_CHANNEL ===
JID: $JID
NAME: $NAME
FOLDER: $FOLDER
TRIGGER: $TRIGGER
REQUIRES_TRIGGER: $REQUIRES_TRIGGER
ASSISTANT_NAME: $ASSISTANT_NAME
NAME_UPDATED: $NAME_UPDATED
STATUS: success
LOG: logs/setup.log
=== END ===
EOF
