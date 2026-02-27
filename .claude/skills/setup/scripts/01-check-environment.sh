#!/bin/bash
set -euo pipefail

# 01-check-environment.sh — Detect OS, Python, uv, container runtimes, existing config

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
LOG_FILE="$PROJECT_ROOT/logs/setup.log"

mkdir -p "$PROJECT_ROOT/logs"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] [check-environment] $*" >> "$LOG_FILE"; }

log "Starting environment check"

# Detect platform
UNAME=$(uname -s)
case "$UNAME" in
  Darwin*) PLATFORM="macos" ;;
  Linux*)  PLATFORM="linux" ;;
  *)       PLATFORM="unknown" ;;
esac
log "Platform: $PLATFORM ($UNAME)"

# Check Python
PYTHON_OK="false"
PYTHON_VERSION="not_found"
if command -v python3 >/dev/null 2>&1; then
  PYTHON_VERSION=$(python3 --version 2>/dev/null | sed 's/^Python //')
  MAJOR=$(echo "$PYTHON_VERSION" | cut -d. -f1)
  MINOR=$(echo "$PYTHON_VERSION" | cut -d. -f2)
  if [ "$MAJOR" -ge 3 ] && [ "$MINOR" -ge 12 ] 2>/dev/null; then
    PYTHON_OK="true"
  fi
  log "Python $PYTHON_VERSION found (major=$MAJOR, minor=$MINOR, ok=$PYTHON_OK)"
else
  log "Python not found"
fi

# Check uv
UV_OK="false"
UV_VERSION="not_found"
if command -v uv >/dev/null 2>&1; then
  UV_OK="true"
  UV_VERSION=$(uv --version 2>/dev/null | sed 's/^uv //')
  log "uv $UV_VERSION found"
else
  log "uv not found"
fi

# Check Apple Container
APPLE_CONTAINER="not_found"
if command -v container >/dev/null 2>&1; then
  APPLE_CONTAINER="installed"
  log "Apple Container: installed ($(which container))"
else
  log "Apple Container: not found"
fi

# Check Docker
DOCKER="not_found"
if command -v docker >/dev/null 2>&1; then
  if docker info >/dev/null 2>&1; then
    DOCKER="running"
    log "Docker: running"
  else
    DOCKER="installed_not_running"
    log "Docker: installed but not running"
  fi
else
  log "Docker: not found"
fi

# Check existing config
HAS_ENV="false"
if [ -f "$PROJECT_ROOT/.env" ]; then
  HAS_ENV="true"
  log ".env file found"
fi

HAS_AUTH="false"
if [ -d "$PROJECT_ROOT/store/auth" ] && [ "$(ls -A "$PROJECT_ROOT/store/auth" 2>/dev/null)" ]; then
  HAS_AUTH="true"
  log "WhatsApp auth credentials found"
fi

HAS_REGISTERED_GROUPS="false"
if [ -f "$PROJECT_ROOT/store/messages.db" ]; then
  RG_COUNT=$(sqlite3 "$PROJECT_ROOT/store/messages.db" "SELECT COUNT(*) FROM registered_groups" 2>/dev/null || echo "0")
  if [ "$RG_COUNT" -gt 0 ] 2>/dev/null; then
    HAS_REGISTERED_GROUPS="true"
    log "Registered groups found in database ($RG_COUNT)"
  fi
fi

log "Environment check complete"

# Output structured status block
cat <<EOF
=== G2 SETUP: CHECK_ENVIRONMENT ===
PLATFORM: $PLATFORM
PYTHON_VERSION: $PYTHON_VERSION
PYTHON_OK: $PYTHON_OK
UV_VERSION: $UV_VERSION
UV_OK: $UV_OK
APPLE_CONTAINER: $APPLE_CONTAINER
DOCKER: $DOCKER
HAS_ENV: $HAS_ENV
HAS_AUTH: $HAS_AUTH
HAS_REGISTERED_GROUPS: $HAS_REGISTERED_GROUPS
STATUS: success
LOG: logs/setup.log
=== END ===
EOF

# Exit 2 if Python is missing or too old
if [ "$PYTHON_OK" = "false" ]; then
  exit 2
fi
