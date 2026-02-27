"""Uninstall a skill via replay-without."""

from __future__ import annotations

import contextlib
import shutil
import subprocess
from pathlib import Path

from .backup import clear_backup, create_backup, restore_backup
from .constants import BASE_DIR
from .lock import acquire_lock
from .path_remap import load_path_remap, resolve_path_remap
from .replay import find_skill_dir, replay_skills
from .state import compute_file_hash, read_state, write_state
from .types import UninstallResult


def uninstall_skill(skill_name: str) -> UninstallResult:
    """Uninstall a skill by replaying all remaining skills without it."""
    project_root = Path.cwd()
    state = read_state()

    # 1. Block after rebase -- skills are baked into base
    if state.rebased_at:
        return UninstallResult(
            success=False,
            skill=skill_name,
            error=(
                "Cannot uninstall individual skills after rebase. The base includes "
                "all skill modifications. To remove a skill, start from a clean core "
                "and re-apply the skills you want."
            ),
        )

    # 2. Verify skill exists
    skill_entry = next((s for s in state.applied_skills if s.name == skill_name), None)
    if not skill_entry:
        return UninstallResult(
            success=False,
            skill=skill_name,
            error=f'Skill "{skill_name}" is not applied.',
        )

    # 3. Check for custom patch -- warn but don't block
    if skill_entry.custom_patch:
        return UninstallResult(
            success=False,
            skill=skill_name,
            custom_patch_warning=(
                f'Skill "{skill_name}" has a custom patch '
                f"({skill_entry.custom_patch_description or 'no description'}). "
                "Uninstalling will lose these customizations. "
                "Re-run with confirmation to proceed."
            ),
        )

    # 4. Acquire lock
    release_lock = acquire_lock()

    try:
        # 4. Backup all files touched by any applied skill
        all_touched_files: set[str] = set()
        for skill in state.applied_skills:
            for file_path in skill.file_hashes:
                all_touched_files.add(file_path)
        if state.custom_modifications:
            for mod in state.custom_modifications:
                for f in mod.files_modified:
                    all_touched_files.add(f)

        files_to_backup = [str(project_root / f) for f in all_touched_files]
        create_backup(files_to_backup)

        # 5. Build remaining skill list (original order, minus removed)
        remaining_skills = [s.name for s in state.applied_skills if s.name != skill_name]

        # 6. Locate all skill dirs
        skill_dirs: dict[str, Path] = {}
        for name in remaining_skills:
            found_dir = find_skill_dir(name, project_root)
            if not found_dir:
                restore_backup()
                clear_backup()
                return UninstallResult(
                    success=False,
                    skill=skill_name,
                    error=(
                        f'Cannot find skill package for "{name}" in .claude/skills/. '
                        "All remaining skills must be available for replay."
                    ),
                )
            skill_dirs[name] = found_dir

        # 7. Reset files exclusive to the removed skill; replay_skills handles the rest
        base_dir = project_root / BASE_DIR
        path_remap = load_path_remap()

        remaining_skill_files: set[str] = set()
        for skill in state.applied_skills:
            if skill.name == skill_name:
                continue
            for file_path in skill.file_hashes:
                remaining_skill_files.add(file_path)

        removed_skill_files = list(skill_entry.file_hashes.keys())
        for file_path in removed_skill_files:
            if file_path in remaining_skill_files:
                continue  # replay_skills handles it
            resolved_path = resolve_path_remap(file_path, path_remap)
            current_path = project_root / resolved_path
            base_path = base_dir / resolved_path

            if base_path.exists():
                current_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(base_path, current_path)
            elif current_path.exists():
                # Add-only file not in base -- remove
                current_path.unlink()

        # 8. Replay remaining skills on clean base
        replay_result = replay_skills(
            skills=remaining_skills,
            skill_dirs=skill_dirs,
            project_root=project_root,
        )

        # 9. Check replay result before proceeding
        if not replay_result.success:
            restore_backup()
            clear_backup()
            return UninstallResult(
                success=False,
                skill=skill_name,
                error=f"Replay failed: {replay_result.error}",
            )

        # 10. Re-apply standalone custom_modifications
        if state.custom_modifications:
            for mod in state.custom_modifications:
                patch_path = project_root / mod.patch_file
                if patch_path.exists():
                    with contextlib.suppress(Exception):
                        subprocess.run(
                            ["git", "apply", "--3way", str(patch_path)],
                            capture_output=True,
                            text=True,
                            check=True,
                            cwd=project_root,
                        )

        # 11. Run skill tests
        replay_results: dict[str, bool] = {}
        for skill in state.applied_skills:
            if skill.name == skill_name:
                continue
            outcomes = skill.structured_outcomes
            if not outcomes or not outcomes.get("test"):
                continue

            try:
                subprocess.run(
                    str(outcomes["test"]),
                    shell=True,
                    capture_output=True,
                    text=True,
                    check=True,
                    cwd=project_root,
                    timeout=120,
                )
                replay_results[skill.name] = True
            except Exception:
                replay_results[skill.name] = False

        # Check for test failures
        test_failures = [name for name, passed in replay_results.items() if not passed]
        if test_failures:
            restore_backup()
            clear_backup()
            return UninstallResult(
                success=False,
                skill=skill_name,
                replay_results=replay_results,
                error=f"Tests failed after uninstall: {', '.join(test_failures)}",
            )

        # 11. Update state
        state.applied_skills = [s for s in state.applied_skills if s.name != skill_name]

        # Update file hashes for remaining skills
        for skill in state.applied_skills:
            new_hashes: dict[str, str] = {}
            for file_path in skill.file_hashes:
                abs_path = project_root / file_path
                if abs_path.exists():
                    new_hashes[file_path] = compute_file_hash(abs_path)
            skill.file_hashes = new_hashes

        write_state(state)

        # 12. Cleanup
        clear_backup()

        return UninstallResult(
            success=True,
            skill=skill_name,
            replay_results=replay_results if replay_results else None,
        )
    except Exception as err:
        restore_backup()
        clear_backup()
        return UninstallResult(
            success=False,
            skill=skill_name,
            error=str(err),
        )
    finally:
        release_lock()
