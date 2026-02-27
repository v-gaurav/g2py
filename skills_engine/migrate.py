"""Initialize and migrate the skills system."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from .constants import BASE_DIR, CUSTOM_DIR
from .init import init_g2_dir
from .state import record_custom_modification


def init_skills_system() -> None:
    """Initialize the skills system by creating the .g2 directory."""
    init_g2_dir()
    print("Skills system initialized. .g2/ directory created.")


def migrate_existing() -> None:
    """Migrate an existing project into the skills system.

    Performs a fresh init, then diffs current files against the base snapshot
    to capture any pre-existing modifications as a migration patch.
    """
    project_root = Path.cwd()

    # First, do a fresh init
    init_g2_dir()

    # Then, diff current files against base to capture modifications
    base_src_dir = project_root / BASE_DIR / "src"
    src_dir = project_root / "src"
    custom_dir = project_root / CUSTOM_DIR
    patch_rel_path = CUSTOM_DIR / "migration.patch"

    try:
        result = subprocess.run(
            ["diff", "-ruN", str(base_src_dir), str(src_dir)],
            capture_output=True,
            text=True,
            check=False,
        )

        # diff exits 0 if no differences, 1 if differences, 2+ on error
        if result.returncode == 2:
            raise subprocess.CalledProcessError(result.returncode, result.args, result.stdout, result.stderr)

        diff = result.stdout

        if diff.strip():
            custom_dir.mkdir(parents=True, exist_ok=True)
            (project_root / patch_rel_path).write_text(diff)

            # Extract modified file paths from the diff
            files_modified = [
                str(Path(m.group(1)).relative_to(project_root))
                for m in re.finditer(r"^diff -ruN .+ (.+)$", diff, re.MULTILINE)
                if not str(Path(m.group(1)).relative_to(project_root)).startswith(".g2")
            ]

            # Record in state so the patch is visible to the tracking system
            record_custom_modification(
                "Pre-skills migration",
                files_modified,
                str(patch_rel_path),
            )

            print("Custom modifications captured in .g2/custom/migration.patch")
        else:
            print("No custom modifications detected.")
    except Exception:
        print("Could not generate diff. Continuing with clean base.")

    print("Migration complete. Skills system ready.")
