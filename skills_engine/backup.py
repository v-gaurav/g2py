"""Backup and restore for the skills engine."""

from __future__ import annotations

import shutil
from pathlib import Path

from .constants import BACKUP_DIR

TOMBSTONE_SUFFIX = ".tombstone"


def _get_backup_dir() -> Path:
    return Path.cwd() / BACKUP_DIR


def create_backup(file_paths: list[str]) -> None:
    """Back up a list of files. Creates tombstones for files that don't exist yet."""
    backup_dir = _get_backup_dir()
    backup_dir.mkdir(parents=True, exist_ok=True)

    for file_path in file_paths:
        abs_path = Path(file_path).resolve()
        relative_path = abs_path.relative_to(Path.cwd())
        backup_path = backup_dir / relative_path
        backup_path.parent.mkdir(parents=True, exist_ok=True)

        if abs_path.exists():
            shutil.copy2(abs_path, backup_path)
        else:
            # File doesn't exist yet -- write a tombstone so restore can delete it
            backup_path.with_name(backup_path.name + TOMBSTONE_SUFFIX).write_text("", encoding="utf-8")


def restore_backup() -> None:
    """Restore all files from the backup directory."""
    backup_dir = _get_backup_dir()
    if not backup_dir.exists():
        return

    def walk(dir_path: Path) -> None:
        for entry in dir_path.iterdir():
            if entry.is_dir():
                walk(entry)
            elif entry.name.endswith(TOMBSTONE_SUFFIX):
                # Tombstone: delete the corresponding project file
                tomb_rel_path = entry.relative_to(backup_dir)
                original_rel = str(tomb_rel_path)[: -len(TOMBSTONE_SUFFIX)]
                original_path = Path.cwd() / original_rel
                if original_path.exists():
                    original_path.unlink()
            else:
                relative_path = entry.relative_to(backup_dir)
                original_path = Path.cwd() / relative_path
                original_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(entry, original_path)

    walk(backup_dir)


def clear_backup() -> None:
    """Remove the entire backup directory."""
    backup_dir = _get_backup_dir()
    if backup_dir.exists():
        shutil.rmtree(backup_dir)
