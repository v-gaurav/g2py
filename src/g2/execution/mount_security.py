"""Mount allowlist validation for containers."""

from __future__ import annotations

import json
from pathlib import Path

from g2.groups.types import AllowedRoot, MountAllowlist
from g2.infrastructure.config import MOUNT_ALLOWLIST_PATH
from g2.infrastructure.logger import logger


def load_mount_allowlist() -> MountAllowlist | None:
    """Load mount allowlist from config file. Returns None if not found."""
    if not MOUNT_ALLOWLIST_PATH.exists():
        return None
    try:
        data = json.loads(MOUNT_ALLOWLIST_PATH.read_text())
        return MountAllowlist(**data)
    except Exception:
        logger.warning("Failed to load mount allowlist", path=str(MOUNT_ALLOWLIST_PATH))
        return None


def _expand_home(p: str) -> str:
    """Expand ~ to home directory."""
    if p.startswith("~"):
        return str(Path.home() / p[2:]) if len(p) > 1 else str(Path.home())
    return p


def validate_mount(
    host_path: str,
    allowlist: MountAllowlist | None,
    is_main: bool,
) -> tuple[bool, bool]:
    """Validate a mount path against the allowlist.

    Returns (allowed, read_only):
        allowed: True if the mount is permitted.
        read_only: True if the mount should be read-only.
    """
    if allowlist is None:
        return True, True  # No allowlist = allow but read-only

    resolved = str(Path(_expand_home(host_path)).resolve())

    # Check blocked patterns
    for pattern in allowlist.blocked_patterns:
        expanded = _expand_home(pattern)
        if resolved.startswith(expanded) or resolved == expanded:
            return False, True

    # Check allowed roots
    for root in allowlist.allowed_roots:
        root_path = str(Path(_expand_home(root.path)).resolve())
        if resolved.startswith(root_path + "/") or resolved == root_path:
            read_only = not root.allow_read_write
            if not is_main and allowlist.non_main_read_only:
                read_only = True
            return True, read_only

    return False, True
