"""Skills engine constants."""

from __future__ import annotations

from pathlib import Path

G2_DIR = Path(".g2")
STATE_FILE = "state.yaml"
BASE_DIR = Path(".g2/base")
BACKUP_DIR = Path(".g2/backup")
LOCK_FILE = Path(".g2/lock")
CUSTOM_DIR = Path(".g2/custom")
RESOLUTIONS_DIR = Path(".g2/resolutions")
SHIPPED_RESOLUTIONS_DIR = Path(".claude/resolutions")
SKILLS_SCHEMA_VERSION = "0.1.0"
