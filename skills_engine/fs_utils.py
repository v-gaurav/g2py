"""Filesystem utilities for the skills engine."""

from __future__ import annotations

import shutil
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


def copy_dir(src: Path, dest: Path) -> None:
    """Recursively copy a directory tree from src to dest.

    Creates destination directories as needed.
    """
    for entry in src.iterdir():
        src_path = entry
        dest_path = dest / entry.name

        if entry.is_dir():
            dest_path.mkdir(parents=True, exist_ok=True)
            copy_dir(src_path, dest_path)
        else:
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_path, dest_path)
