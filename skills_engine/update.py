"""Preview and apply core updates with three-way merge."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Any

import yaml

from .backup import clear_backup, create_backup, restore_backup
from .constants import BASE_DIR
from .customize import is_customize_active
from .fs_utils import copy_dir
from .lock import acquire_lock
from .merge import (
    cleanup_merge_state,
    is_git_repo,
    merge_file,
    run_rerere,
    setup_rerere_adapter,
)
from .path_remap import record_path_remap
from .state import compute_file_hash, read_state, write_state
from .structured import (
    merge_docker_compose_services,
    merge_env_additions,
    merge_npm_dependencies,
    run_npm_install,
)
from .types import UpdatePreview, UpdateResult


def _walk_dir(directory: Path, root: Path | None = None) -> list[str]:
    """Recursively walk a directory and return relative paths of all files."""
    root_dir = root or directory
    results: list[str] = []
    for entry in directory.iterdir():
        if entry.is_dir():
            results.extend(_walk_dir(entry, root_dir))
        else:
            results.append(str(entry.relative_to(root_dir)))
    return results


def preview_update(new_core_path: str | Path) -> UpdatePreview:
    """Preview what a core update would change."""
    new_core_path = Path(new_core_path)
    project_root = Path.cwd()
    state = read_state()
    base_dir = project_root / BASE_DIR

    # Read new version from package.json in new_core_path
    new_pkg_path = new_core_path / "package.json"
    new_version = "unknown"
    if new_pkg_path.exists():
        import json

        pkg = json.loads(new_pkg_path.read_text())
        new_version = pkg.get("version", "unknown")

    # Walk all files in new_core_path, compare against base to find changed files
    new_core_files = _walk_dir(new_core_path)
    files_changed: list[str] = []
    files_deleted: list[str] = []

    for rel_path in new_core_files:
        base_path = base_dir / rel_path
        new_path = new_core_path / rel_path

        if not base_path.exists():
            files_changed.append(rel_path)
            continue

        base_hash = compute_file_hash(base_path)
        new_hash = compute_file_hash(new_path)
        if base_hash != new_hash:
            files_changed.append(rel_path)

    # Detect files deleted in the new core (exist in base but not in new_core_path)
    if base_dir.exists():
        base_files = _walk_dir(base_dir)
        new_core_set = set(new_core_files)
        for rel_path in base_files:
            if rel_path not in new_core_set:
                files_deleted.append(rel_path)

    # Check which changed files have skill overlaps
    conflict_risk: list[str] = []
    custom_patches_at_risk: list[str] = []

    for rel_path in files_changed:
        # Check applied skills
        for skill in state.applied_skills:
            if rel_path in skill.file_hashes:
                conflict_risk.append(rel_path)
                break

        # Check custom modifications
        if state.custom_modifications:
            for mod in state.custom_modifications:
                if rel_path in mod.files_modified:
                    custom_patches_at_risk.append(rel_path)
                    break

    return UpdatePreview(
        current_version=state.core_version,
        new_version=new_version,
        files_changed=files_changed,
        files_deleted=files_deleted,
        conflict_risk=conflict_risk,
        custom_patches_at_risk=custom_patches_at_risk,
    )


def apply_update(new_core_path: str | Path) -> UpdateResult:
    """Apply a core update with three-way merge and conflict resolution."""
    new_core_path = Path(new_core_path)
    project_root = Path.cwd()
    state = read_state()
    base_dir = project_root / BASE_DIR

    # --- Pre-flight ---
    if is_customize_active():
        return UpdateResult(
            success=False,
            previous_version=state.core_version,
            new_version="unknown",
            error="A customize session is active. Run commit_customize() or abort_customize() first.",
        )

    release_lock = acquire_lock()

    try:
        # --- Preview ---
        preview = preview_update(new_core_path)

        # --- Backup ---
        files_to_backup = [
            *[str(project_root / f) for f in preview.files_changed],
            *[str(project_root / f) for f in preview.files_deleted],
        ]
        create_backup(files_to_backup)

        # --- Three-way merge ---
        merge_conflicts: list[str] = []

        for rel_path in preview.files_changed:
            current_path = project_root / rel_path
            base_path = base_dir / rel_path
            new_core_src_path = new_core_path / rel_path

            if not current_path.exists():
                # File doesn't exist yet -- just copy from new core
                current_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(new_core_src_path, current_path)
                continue

            if not base_path.exists():
                # No base -- use current as base
                base_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(current_path, base_path)

            # Three-way merge: current <- base -> new_core
            # Save current content before merge overwrites it (needed for rerere stage 2 = "ours")
            ours_content = current_path.read_text()
            tmp_current = Path(tempfile.gettempdir()) / (f"g2-update-{uuid.uuid4()}-{Path(rel_path).name}")
            shutil.copy2(current_path, tmp_current)

            result = merge_file(tmp_current, base_path, new_core_src_path)

            if result.clean:
                shutil.copy2(tmp_current, current_path)
                tmp_current.unlink()
            else:
                # Copy conflict markers to working tree path before rerere
                shutil.copy2(tmp_current, current_path)
                tmp_current.unlink()

                if is_git_repo():
                    base_content = base_path.read_text()
                    theirs_content = new_core_src_path.read_text()

                    setup_rerere_adapter(rel_path, base_content, ours_content, theirs_content)
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

                merge_conflicts.append(rel_path)

        if merge_conflicts:
            # Preserve backup so user can resolve conflicts manually, then continue
            return UpdateResult(
                success=False,
                previous_version=preview.current_version,
                new_version=preview.new_version,
                merge_conflicts=merge_conflicts,
                backup_pending=True,
                error=(
                    f"Unresolved merge conflicts in: {', '.join(merge_conflicts)}. "
                    "Resolve manually then call clear_backup(), or "
                    "restore_backup() + clear_backup() to abort."
                ),
            )

        # --- Remove deleted files ---
        for rel_path in preview.files_deleted:
            current_path = project_root / rel_path
            if current_path.exists():
                current_path.unlink()

        # --- Re-apply custom patches ---
        custom_patch_failures: list[str] = []
        if state.custom_modifications:
            for mod in state.custom_modifications:
                patch_path = project_root / mod.patch_file
                if not patch_path.exists():
                    custom_patch_failures.append(f"{mod.description}: patch file missing ({mod.patch_file})")
                    continue
                try:
                    subprocess.run(
                        ["git", "apply", "--3way", str(patch_path)],
                        capture_output=True,
                        text=True,
                        check=True,
                        cwd=project_root,
                    )
                except Exception:
                    custom_patch_failures.append(mod.description)

        # --- Record path remaps from update metadata ---
        remap_file = new_core_path / ".g2-meta" / "path_remap.yaml"
        if remap_file.exists():
            remap = yaml.safe_load(remap_file.read_text())
            if remap and isinstance(remap, dict):
                record_path_remap(remap)

        # --- Update base ---
        if base_dir.exists():
            shutil.rmtree(base_dir)
        base_dir.mkdir(parents=True, exist_ok=True)
        copy_dir(new_core_path, base_dir)

        # --- Structured ops: re-apply from all skills ---
        all_npm_deps: dict[str, str] = {}
        all_env_additions: list[str] = []
        all_docker_services: dict[str, Any] = {}
        has_npm_deps = False

        for skill in state.applied_skills:
            outcomes = skill.structured_outcomes
            if not outcomes:
                continue

            if outcomes.get("npm_dependencies"):
                all_npm_deps.update(outcomes["npm_dependencies"])
                has_npm_deps = True
            if outcomes.get("env_additions"):
                all_env_additions.extend(outcomes["env_additions"])
            if outcomes.get("docker_compose_services"):
                all_docker_services.update(outcomes["docker_compose_services"])

        if has_npm_deps:
            pkg_path = project_root / "package.json"
            merge_npm_dependencies(pkg_path, all_npm_deps)

        if all_env_additions:
            env_path = project_root / ".env.example"
            merge_env_additions(env_path, all_env_additions)

        if all_docker_services:
            compose_path = project_root / "docker-compose.yml"
            merge_docker_compose_services(compose_path, all_docker_services)

        if has_npm_deps:
            run_npm_install()

        # --- Run tests for each applied skill ---
        skill_reapply_results: dict[str, bool] = {}

        for skill in state.applied_skills:
            outcomes = skill.structured_outcomes
            if not outcomes or not outcomes.get("test"):
                continue

            test_cmd = str(outcomes["test"])
            try:
                subprocess.run(
                    test_cmd,
                    shell=True,
                    capture_output=True,
                    text=True,
                    check=True,
                    cwd=project_root,
                    timeout=120,
                )
                skill_reapply_results[skill.name] = True
            except Exception:
                skill_reapply_results[skill.name] = False

        # --- Update state ---
        state.core_version = preview.new_version
        write_state(state)

        # --- Cleanup ---
        clear_backup()

        return UpdateResult(
            success=True,
            previous_version=preview.current_version,
            new_version=preview.new_version,
            custom_patch_failures=custom_patch_failures if custom_patch_failures else None,
            skill_reapply_results=skill_reapply_results if skill_reapply_results else None,
        )
    except Exception as err:
        restore_backup()
        clear_backup()
        return UpdateResult(
            success=False,
            previous_version=state.core_version,
            new_version="unknown",
            error=str(err),
        )
    finally:
        release_lock()
