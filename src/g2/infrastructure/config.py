"""Configuration constants, .env parsing, and timeout settings."""

from __future__ import annotations

import os
import re
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def read_env_file(keys: list[str]) -> dict[str, str]:
    """Parse .env file and return values for requested keys.

    Does NOT load into os.environ — callers decide what to do with values.
    This keeps secrets out of the process environment so they don't leak
    to child processes.
    """
    env_file = Path.cwd() / ".env"
    try:
        content = env_file.read_text()
    except OSError:
        return {}

    result: dict[str, str] = {}
    wanted = set(keys)

    for line in content.splitlines():
        trimmed = line.strip()
        if not trimmed or trimmed.startswith("#"):
            continue
        eq_idx = trimmed.find("=")
        if eq_idx == -1:
            continue
        key = trimmed[:eq_idx].strip()
        if key not in wanted:
            continue
        value = trimmed[eq_idx + 1 :].strip()
        if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
            value = value[1:-1]
        if value:
            result[key] = value

    return result


# Read config values from .env (falls back to os.environ).
_env_config = read_env_file(["ASSISTANT_NAME", "ASSISTANT_HAS_OWN_NUMBER"])

ASSISTANT_NAME: str = os.environ.get("ASSISTANT_NAME") or _env_config.get("ASSISTANT_NAME", "G2")
ASSISTANT_HAS_OWN_NUMBER: bool = (
    os.environ.get("ASSISTANT_HAS_OWN_NUMBER") or _env_config.get("ASSISTANT_HAS_OWN_NUMBER", "")
) == "true"

POLL_INTERVAL: float = 2.0  # seconds
SCHEDULER_POLL_INTERVAL: float = 60.0
GMAIL_POLL_INTERVAL: float = 60.0
GMAIL_TRIGGER_ADDRESS: str = os.environ.get("GMAIL_TRIGGER_ADDRESS", "vijaywargiag+2@gmail.com")
GMAIL_GROUP_FOLDER: str = "email"

# Absolute paths
PROJECT_ROOT: Path = Path.cwd()
HOME_DIR: Path = Path.home()

MOUNT_ALLOWLIST_PATH: Path = HOME_DIR / ".config" / "g2" / "mount-allowlist.json"
STORE_DIR: Path = (PROJECT_ROOT / "store").resolve()
GROUPS_DIR: Path = (PROJECT_ROOT / "groups").resolve()
DATA_DIR: Path = (PROJECT_ROOT / "data").resolve()
MAIN_GROUP_FOLDER: str = "main"

CONTAINER_IMAGE: str = os.environ.get("CONTAINER_IMAGE", "g2-agent:latest")
CONTAINER_TIMEOUT: int = int(os.environ.get("CONTAINER_TIMEOUT", "1800000"))
CONTAINER_MAX_OUTPUT_SIZE: int = int(os.environ.get("CONTAINER_MAX_OUTPUT_SIZE", "10485760"))  # 10MB
IPC_POLL_INTERVAL: float = 1.0
IDLE_TIMEOUT: int = int(os.environ.get("IDLE_TIMEOUT", "1800000"))  # 30min
MAX_CONCURRENT_CONTAINERS: int = max(1, int(os.environ.get("MAX_CONCURRENT_CONTAINERS", "5")))


def _escape_regex(s: str) -> str:
    return re.escape(s)


TRIGGER_PATTERN: re.Pattern[str] = re.compile(rf"^@{_escape_regex(ASSISTANT_NAME)}\b", re.IGNORECASE)


def _resolve_timezone() -> str:
    tz = os.environ.get("TZ", "")
    if not tz:
        try:
            import time

            tz = time.tzname[0] or "UTC"
            # Try to get the proper IANA timezone
            import locale

            try:
                # On Linux, read /etc/timezone or use the TZ symlink
                tz_file = Path("/etc/timezone")
                if tz_file.exists():
                    tz = tz_file.read_text().strip()
                else:
                    local_tz = Path("/etc/localtime").resolve()
                    # Extract IANA name from path like /usr/share/zoneinfo/America/New_York
                    parts = local_tz.parts
                    zi_idx = parts.index("zoneinfo") if "zoneinfo" in parts else -1
                    if zi_idx >= 0:
                        tz = "/".join(parts[zi_idx + 1 :])
            except Exception:
                pass
        except Exception:
            tz = "UTC"

    if not tz:
        return "UTC"

    try:
        ZoneInfo(tz)
        return tz
    except (ZoneInfoNotFoundError, KeyError):
        return "UTC"


TIMEZONE: str = _resolve_timezone()


class TimeoutConfig:
    """Timeout configuration for container execution."""

    def __init__(self, container_timeout: int = CONTAINER_TIMEOUT, idle_timeout: int = IDLE_TIMEOUT) -> None:
        self.container_timeout = container_timeout
        self.idle_timeout = idle_timeout

    def get_hard_timeout(self) -> int:
        """Get the hard timeout (ensures idle timeout can trigger before hard kill)."""
        return max(self.container_timeout, self.idle_timeout + 30_000)

    def for_group(self, group: object) -> TimeoutConfig:
        """Create a TimeoutConfig for a specific group, using group's custom timeout if set."""
        container_config = getattr(group, "container_config", None)
        group_timeout = (container_config.timeout if container_config and container_config.timeout else self.container_timeout)
        return TimeoutConfig(group_timeout, self.idle_timeout)
