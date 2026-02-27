"""Rebase skills by flattening into a new base or merging with a new base path."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path

from .backup import clear_backup, create_backup, restore_backup
from .constants import BASE_DIR, G2_DIR
from .fs_utils import copy_dir
from .lock import acquire_lock
from .merge import (
    cleanup_merge_state,
    is_git_repo,
    merge_file,
    run_rerere,
    setup_rerere_adapter,
)
from .resolution_cache import clear_all_resolutions
from .state import compute_file_hash, read_state, write_state
from .types import RebaseResult, SkillState


def _walk_dir(directory: Path, root: Path) -> list[str]:
    """Recursively walk a directory and return relative paths of all files."""
    results: list[str] = []
    if not directory.exists():
        return results

    for entry in directory.iterdir():
        if entry.is_dir():
            results.extend(_walk_dir(entry, root))
        else:
            results.append(str(entry.relative_to(root)))
    return results


def _collect_tracked_files(state: SkillState) -> set[str]:
    """Collect all file paths tracked by applied skills and custom modifications."""
    tracked: set[str] = set()

    for skill in state.applied_skills:
        for rel_path in skill.file_hashes:
            tracked.add(rel_path)

    if state.custom_modifications:
        for mod in state.custom_modifications:
            for rel_path in mod.files_modified:
                tracked.add(rel_path)

    return tracked


def rebase(new_base_path: str | Path | None = None) -> RebaseResult:
    """Rebase skills onto a new base or flatten current state into the base.

    If new_base_path is provided, performs a three-way merge with the new base.
    Otherwise, flattens all current skill modifications into the base.
    """
    project_root = Path.cwd()
    state = read_state()

    if len(state.applied_skills) == 0:
        return RebaseResult(
            success=False,
            files_in_patch=0,
            error="No skills applied. Nothing to rebase.",
        )

    release_lock = acquire_lock()

    try:
        tracked_files = _collect_tracked_files(state)
        base_abs_dir = project_root / BASE_DIR

        # Include base dir files
        base_files = _walk_dir(base_abs_dir, base_abs_dir)
        for f in base_files:
            tracked_files.add(f)

        # Backup
        files_to_backup: list[str] = []
        for rel_path in tracked_files:
            abs_path = project_root / rel_path
            if abs_path.exists():
                files_to_backup.append(str(abs_path))
            base_file_path = base_abs_dir / rel_path
            if base_file_path.exists():
                files_to_backup.append(str(base_file_path))
        state_file_path = project_root / G2_DIR / "state.yaml"
        files_to_backup.append(str(state_file_path))
        create_backup(files_to_backup)

        try:
            # Generate unified diff: base vs working tree (archival record)
            combined_patch = ""
            files_in_patch = 0

            for rel_path in tracked_files:
                base_path = base_abs_dir / rel_path
                working_path = project_root / rel_path

                old_path = str(base_path) if base_path.exists() else "/dev/null"
                new_path = str(working_path) if working_path.exists() else "/dev/null"

                if old_path == "/dev/null" and new_path == "/dev/null":
                    continue

                result = subprocess.run(
                    ["diff", "-ruN", old_path, new_path],
                    capture_output=True,
                    text=True,
                    check=False,
                )

                # diff exits 0 if identical, 1 if different, 2+ on error
                if result.returncode == 1 and result.stdout or result.returncode == 0 and result.stdout.strip():
                    combined_patch += result.stdout
                    files_in_patch += 1
                elif result.returncode >= 2:
                    raise subprocess.CalledProcessError(
                        result.returncode,
                        result.args,
                        result.stdout,
                        result.stderr,
                    )

            # Save combined patch
            patch_path = project_root / G2_DIR / "combined.patch"
            patch_path.write_text(combined_patch)

            if new_base_path is not None:
                # --- Rebase with new base: three-way merge with resolution model ---
                abs_new_base = Path(new_base_path).resolve()

                # Save current working tree content before overwriting
                saved_content: dict[str, str] = {}
                for rel_path in tracked_files:
                    working_path = project_root / rel_path
                    if working_path.exists():
                        saved_content[rel_path] = working_path.read_text()

                # Replace base
                if base_abs_dir.exists():
                    shutil.rmtree(base_abs_dir)
                base_abs_dir.mkdir(parents=True, exist_ok=True)
                copy_dir(abs_new_base, base_abs_dir)

                # Copy new base to working tree
                copy_dir(abs_new_base, project_root)

                # Three-way merge per file: new-base <- old-base -> saved-working-tree
                merge_conflicts: list[str] = []

                for rel_path in tracked_files:
                    new_base_src = abs_new_base / rel_path
                    current_path = project_root / rel_path
                    saved = saved_content.get(rel_path)

                    if not saved:
                        continue  # No working tree content to merge
                    if not new_base_src.exists():
                        # File only existed in working tree, not in new base -- restore it
                        current_path.parent.mkdir(parents=True, exist_ok=True)
                        current_path.write_text(saved)
                        continue

                    new_base_content = new_base_src.read_text()
                    if new_base_content == saved:
                        continue  # No diff

                    # Find old base content from backup
                    old_base_path = project_root / ".g2" / "backup" / BASE_DIR / rel_path
                    if not old_base_path.exists():
                        # No old base -- keep saved content
                        current_path.write_text(saved)
                        continue

                    # Save "ours" (new base content) before merge overwrites it
                    ours_content = new_base_content

                    # Three-way merge: current(new base) <- old-base -> saved(modifications)
                    tmp_saved = Path(tempfile.gettempdir()) / (f"g2-rebase-{uuid.uuid4()}-{Path(rel_path).name}")
                    tmp_saved.write_text(saved)

                    result = merge_file(current_path, old_base_path, tmp_saved)
                    tmp_saved.unlink()

                    if not result.clean:
                        # Try rerere resolution (three-level model)
                        if is_git_repo():
                            base_content = old_base_path.read_text()
                            setup_rerere_adapter(rel_path, base_content, ours_content, saved)
                            auto_resolved = run_rerere(str(current_path))

                            if auto_resolved:
                                subprocess.run(
                                    ["git", "add", rel_path],
                                    capture_output=True,
                                    text=True,
                                    check=False,
                                )
                                subprocess.run(
                                    ["git", "rerere"],
                                    capture_output=True,
                                    text=True,
                                    check=False,
                                )
                                cleanup_merge_state(rel_path)
                                continue

                            cleanup_merge_state(rel_path)

                        # Unresolved -- conflict markers remain in working tree
                        merge_conflicts.append(rel_path)

                if merge_conflicts:
                    # Return with backup pending for resolution
                    return RebaseResult(
                        success=False,
                        patch_file=str(patch_path),
                        files_in_patch=files_in_patch,
                        merge_conflicts=merge_conflicts,
                        backup_pending=True,
                        error=(
                            f"Merge conflicts in: {', '.join(merge_conflicts)}. "
                            "Resolve manually then call clear_backup(), or "
                            "restore_backup() + clear_backup() to abort."
                        ),
                    )
            else:
                # --- Rebase without new base: flatten into base ---
                # Update base to current working tree state (all skills baked in)
                for rel_path in tracked_files:
                    working_path = project_root / rel_path
                    base_path = base_abs_dir / rel_path

                    if working_path.exists():
                        base_path.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(working_path, base_path)
                    elif base_path.exists():
                        # File was removed by skills -- remove from base too
                        base_path.unlink()

            # Update state
            now = datetime.now(UTC).isoformat()

            for skill in state.applied_skills:
                updated_hashes: dict[str, str] = {}
                for rel_path in skill.file_hashes:
                    abs_path = project_root / rel_path
                    if abs_path.exists():
                        updated_hashes[rel_path] = compute_file_hash(abs_path)
                skill.file_hashes = updated_hashes

            state.custom_modifications = None
            state.rebased_at = now
            write_state(state)

            # Clear stale resolution cache (base has changed, old resolutions invalid)
            clear_all_resolutions(project_root)

            clear_backup()

            return RebaseResult(
                success=True,
                patch_file=str(patch_path),
                files_in_patch=files_in_patch,
                rebased_at=now,
            )
        except Exception:
            restore_backup()
            clear_backup()
            raise
    finally:
        release_lock()
