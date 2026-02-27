"""Customize session management for tracking user modifications to skill-managed files."""

from __future__ import annotations

import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import yaml
from pydantic import BaseModel

from .constants import BASE_DIR, CUSTOM_DIR
from .state import compute_file_hash, read_state, record_custom_modification


class PendingCustomize(BaseModel):
    """Tracks an active customize session."""

    description: str
    started_at: str
    file_hashes: dict[str, str]


def _get_pending_path() -> Path:
    """Return the path to the pending customize session file."""
    return Path.cwd() / CUSTOM_DIR / "pending.yaml"


def is_customize_active() -> bool:
    """Check if a customize session is currently active."""
    return _get_pending_path().exists()


def start_customize(description: str) -> None:
    """Start a new customize session, capturing current file hashes.

    Raises RuntimeError if a session is already active.
    """
    if is_customize_active():
        raise RuntimeError("A customize session is already active. Commit or abort it first.")

    state = read_state()

    # Collect all file hashes from applied skills
    file_hashes: dict[str, str] = {}
    for skill in state.applied_skills:
        for relative_path, hash_val in skill.file_hashes.items():
            file_hashes[relative_path] = hash_val

    pending = PendingCustomize(
        description=description,
        started_at=datetime.now(UTC).isoformat(),
        file_hashes=file_hashes,
    )

    custom_dir = Path.cwd() / CUSTOM_DIR
    custom_dir.mkdir(parents=True, exist_ok=True)
    _get_pending_path().write_text(yaml.dump(pending.model_dump(), default_flow_style=False))


def commit_customize() -> None:
    """Commit a customize session, generating a patch file for the changes.

    Detects which skill-managed files changed, generates unified diffs,
    and records the custom modification in state.
    """
    pending_path = _get_pending_path()
    if not pending_path.exists():
        raise RuntimeError("No active customize session. Run start_customize() first.")

    raw = yaml.safe_load(pending_path.read_text())
    pending = PendingCustomize.model_validate(raw)
    cwd = Path.cwd()

    # Find files that changed
    changed_files: list[str] = []
    for relative_path in pending.file_hashes:
        full_path = cwd / relative_path
        if not full_path.exists():
            # File was deleted -- counts as changed
            changed_files.append(relative_path)
            continue
        current_hash = compute_file_hash(full_path)
        if current_hash != pending.file_hashes[relative_path]:
            changed_files.append(relative_path)

    if not changed_files:
        print("No files changed during customize session. Nothing to commit.")
        pending_path.unlink()
        return

    # Generate unified diff for each changed file
    base_dir = cwd / BASE_DIR
    combined_patch = ""

    for relative_path in changed_files:
        base_path = base_dir / relative_path
        current_path = cwd / relative_path

        # Use /dev/null if either side doesn't exist
        old_path = str(base_path) if base_path.exists() else "/dev/null"
        new_path = str(current_path) if current_path.exists() else "/dev/null"

        result = subprocess.run(
            ["diff", "-ruN", old_path, new_path],
            capture_output=True,
            text=True,
        )

        if result.returncode == 0:
            # Files are identical (shouldn't happen since we detected a change)
            combined_patch += result.stdout
        elif result.returncode == 1:
            # diff exits 1 when files differ -- that's expected
            combined_patch += result.stdout
        elif result.returncode == 2:
            raise RuntimeError(
                f"diff error for {relative_path}: diff exited with status 2 (check file permissions or encoding)"
            )
        else:
            raise RuntimeError(f"diff failed for {relative_path} with exit code {result.returncode}")

    if not combined_patch.strip():
        print("Diff was empty despite hash changes. Nothing to commit.")
        pending_path.unlink()
        return

    # Determine sequence number
    state = read_state()
    existing_count = len(state.custom_modifications) if state.custom_modifications else 0
    seq_num = str(existing_count + 1).zfill(3)

    # Sanitize description for filename
    sanitized = re.sub(r"[^a-z0-9]+", "-", pending.description.lower())
    sanitized = sanitized.strip("-")
    patch_filename = f"{seq_num}-{sanitized}.patch"
    patch_rel_path = str(CUSTOM_DIR / patch_filename)
    patch_full_path = cwd / patch_rel_path

    patch_full_path.write_text(combined_patch)
    record_custom_modification(pending.description, changed_files, patch_rel_path)
    pending_path.unlink()


def abort_customize() -> None:
    """Abort the current customize session, discarding the pending state."""
    pending_path = _get_pending_path()
    if pending_path.exists():
        pending_path.unlink()
