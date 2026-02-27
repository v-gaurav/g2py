"""Initialize the .g2 directory and base snapshot."""

from __future__ import annotations

import contextlib
import json
import shutil
import subprocess
from pathlib import Path

from .constants import BACKUP_DIR, BASE_DIR
from .merge import is_git_repo
from .state import write_state
from .types import SkillState

# Top-level paths to include in base snapshot
BASE_INCLUDES = ["src/", "package.json", ".env.example", "container/"]

# Directories/files to always exclude from base snapshot
BASE_EXCLUDES = {
    "node_modules",
    ".g2",
    ".git",
    "dist",
    "data",
    "groups",
    "store",
    "logs",
}


def init_g2_dir() -> None:
    """Initialize the .g2 directory with base snapshot and initial state."""
    project_root = Path.cwd()
    base_dir = project_root / BASE_DIR

    # Create structure
    (project_root / BACKUP_DIR).mkdir(parents=True, exist_ok=True)

    # Clean existing base
    if base_dir.exists():
        shutil.rmtree(base_dir)
    base_dir.mkdir(parents=True, exist_ok=True)

    # Snapshot all included paths
    for include in BASE_INCLUDES:
        src_path = project_root / include
        if not src_path.exists():
            continue

        dest_path = base_dir / include

        if src_path.is_dir():
            _copy_dir_filtered(src_path, dest_path, BASE_EXCLUDES)
        else:
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_path, dest_path)

    # Create initial state
    core_version = _get_core_version(project_root)
    initial_state = SkillState(
        skills_system_version="0.1.0",
        core_version=core_version,
        applied_skills=[],
    )
    write_state(initial_state)

    # Enable git rerere if in a git repo
    if is_git_repo():
        with contextlib.suppress(Exception):
            subprocess.run(
                ["git", "config", "--local", "rerere.enabled", "true"],
                capture_output=True,
                text=True,
                check=False,
            )


def _copy_dir_filtered(
    src: Path,
    dest: Path,
    excludes: set[str],
) -> None:
    """Recursively copy a directory tree, excluding specified names."""
    dest.mkdir(parents=True, exist_ok=True)

    for entry in src.iterdir():
        if entry.name in excludes:
            continue

        src_path = entry
        dest_path = dest / entry.name

        if entry.is_dir():
            _copy_dir_filtered(src_path, dest_path, excludes)
        else:
            shutil.copy2(src_path, dest_path)


def _get_core_version(project_root: Path) -> str:
    """Read the core version from package.json."""
    try:
        pkg_path = project_root / "package.json"
        pkg = json.loads(pkg_path.read_text())
        return pkg.get("version", "0.0.0")
    except Exception:
        return "0.0.0"
