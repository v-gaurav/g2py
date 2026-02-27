"""File-based locking for the skills engine."""

from __future__ import annotations

import contextlib
import json
import os
import time
from pathlib import Path
from typing import TYPE_CHECKING

from .constants import LOCK_FILE

if TYPE_CHECKING:
    from collections.abc import Callable

STALE_TIMEOUT_S = 5 * 60  # 5 minutes


class LockInfo:
    def __init__(self, pid: int, timestamp: float) -> None:
        self.pid = pid
        self.timestamp = timestamp

    def to_dict(self) -> dict[str, int | float]:
        return {"pid": self.pid, "timestamp": self.timestamp}

    @classmethod
    def from_dict(cls, data: dict[str, int | float]) -> LockInfo:
        return cls(pid=int(data["pid"]), timestamp=float(data["timestamp"]))


def _get_lock_path() -> Path:
    return Path.cwd() / LOCK_FILE


def _is_stale(lock: LockInfo) -> bool:
    return time.time() - lock.timestamp > STALE_TIMEOUT_S


def _is_process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def acquire_lock() -> Callable[[], None]:
    """Acquire an exclusive file lock. Returns a release function."""
    lock_path = _get_lock_path()
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    lock_info = LockInfo(pid=os.getpid(), timestamp=time.time())

    try:
        # Atomic creation -- fails if file already exists
        fd = os.open(str(lock_path), os.O_WRONLY | os.O_CREAT | os.O_EXCL)
        try:
            os.write(fd, json.dumps(lock_info.to_dict()).encode())
        finally:
            os.close(fd)
        return release_lock
    except FileExistsError:
        # Lock file exists -- check if it's stale or from a dead process
        try:
            existing = LockInfo.from_dict(json.loads(lock_path.read_text(encoding="utf-8")))
            if not _is_stale(existing) and _is_process_alive(existing.pid):
                ts_iso = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(existing.timestamp))
                raise RuntimeError(
                    f"Operation in progress (pid {existing.pid}, started {ts_iso}). "
                    f"If this is stale, delete {LOCK_FILE}"
                )
            # Stale or dead process -- overwrite
        except RuntimeError:
            raise
        except Exception:
            # Corrupt or unreadable -- overwrite
            pass

        with contextlib.suppress(FileNotFoundError):
            lock_path.unlink()

        try:
            fd = os.open(str(lock_path), os.O_WRONLY | os.O_CREAT | os.O_EXCL)
            try:
                os.write(fd, json.dumps(lock_info.to_dict()).encode())
            finally:
                os.close(fd)
        except FileExistsError as err:
            raise RuntimeError("Lock contention: another process acquired the lock. Retry.") from err

        return release_lock


def release_lock() -> None:
    """Release the lock if it belongs to the current process."""
    lock_path = _get_lock_path()
    if lock_path.exists():
        try:
            lock = LockInfo.from_dict(json.loads(lock_path.read_text(encoding="utf-8")))
            # Only release our own lock
            if lock.pid == os.getpid():
                lock_path.unlink()
        except Exception:
            # Corrupt or missing -- safe to remove
            with contextlib.suppress(FileNotFoundError):
                lock_path.unlink()


def is_locked() -> bool:
    """Check whether a valid (non-stale) lock is held."""
    lock_path = _get_lock_path()
    if not lock_path.exists():
        return False

    try:
        lock = LockInfo.from_dict(json.loads(lock_path.read_text(encoding="utf-8")))
        return not _is_stale(lock) and _is_process_alive(lock.pid)
    except Exception:
        return False
