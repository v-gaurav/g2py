"""Apply a skill to the current project."""

from __future__ import annotations

import contextlib
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path

from .backup import clear_backup, create_backup, restore_backup
from .constants import G2_DIR
from .customize import is_customize_active
from .file_ops import execute_file_ops
from .lock import acquire_lock
from .manifest import (
    check_conflicts,
    check_core_version,
    check_dependencies,
    check_system_version,
    read_manifest,
)
from .merge import (
    cleanup_merge_state,
    is_git_repo,
    merge_file,
    run_rerere,
    setup_rerere_adapter,
)
from .path_remap import load_path_remap, resolve_path_remap
from .resolution_cache import load_resolutions
from .state import compute_file_hash, read_state, record_skill_application, write_state
from .structured import (
    merge_docker_compose_services,
    merge_env_additions,
    merge_npm_dependencies,
    run_npm_install,
)
from .types import ApplyResult


def apply_skill(skill_dir: str | Path) -> ApplyResult:
    """Apply a skill from the given skill directory to the current project."""
    skill_dir = Path(skill_dir)
    project_root = Path.cwd()
    manifest = read_manifest(skill_dir)

    # --- Pre-flight checks ---
    current_state = read_state()

    # Check skills system version compatibility
    sys_check = check_system_version(manifest)
    if not sys_check["ok"]:
        return ApplyResult(
            success=False,
            skill=manifest.skill,
            version=manifest.version,
            error=sys_check.get("error"),
        )

    # Check core version compatibility
    core_check = check_core_version(manifest)
    if core_check.get("warning"):
        print(f"Warning: {core_check['warning']}")

    # Block if customize session is active
    if is_customize_active():
        return ApplyResult(
            success=False,
            skill=manifest.skill,
            version=manifest.version,
            error="A customize session is active. Run commit_customize() or abort_customize() first.",
        )

    deps = check_dependencies(manifest)
    if not deps["ok"]:
        return ApplyResult(
            success=False,
            skill=manifest.skill,
            version=manifest.version,
            error=f"Missing dependencies: {', '.join(deps['missing'])}",
        )

    conflicts = check_conflicts(manifest)
    if not conflicts["ok"]:
        return ApplyResult(
            success=False,
            skill=manifest.skill,
            version=manifest.version,
            error=f"Conflicting skills: {', '.join(conflicts['conflicting'])}",
        )

    # Load path remap for renamed core files
    path_remap = load_path_remap()

    # Detect drift for modified files
    drift_files: list[str] = []
    for rel_path in manifest.modifies:
        resolved_path = resolve_path_remap(rel_path, path_remap)
        current_path = project_root / resolved_path
        base_path = project_root / G2_DIR / "base" / resolved_path

        if current_path.exists() and base_path.exists():
            current_hash = compute_file_hash(current_path)
            base_hash = compute_file_hash(base_path)
            if current_hash != base_hash:
                drift_files.append(rel_path)

    if drift_files:
        print(f"Drift detected in: {', '.join(drift_files)}")
        print("Three-way merge will be used to reconcile changes.")

    # --- Acquire lock ---
    release_lock = acquire_lock()

    # Track added files so we can remove them on rollback
    added_files: list[Path] = []

    try:
        # --- Backup ---
        files_to_backup = [
            *[str(project_root / resolve_path_remap(f, path_remap)) for f in manifest.modifies],
            *[str(project_root / resolve_path_remap(f, path_remap)) for f in manifest.adds],
            *[
                str(project_root / resolve_path_remap(op.from_, path_remap))
                for op in (manifest.file_ops or [])
                if op.from_
            ],
            str(project_root / "package.json"),
            str(project_root / "package-lock.json"),
            str(project_root / ".env.example"),
            str(project_root / "docker-compose.yml"),
        ]
        create_backup(files_to_backup)

        # --- File operations (before copy adds, per architecture doc) ---
        if manifest.file_ops and len(manifest.file_ops) > 0:
            file_ops_result = execute_file_ops(manifest.file_ops, project_root)
            if not file_ops_result.success:
                restore_backup()
                clear_backup()
                return ApplyResult(
                    success=False,
                    skill=manifest.skill,
                    version=manifest.version,
                    error=f"File operations failed: {'; '.join(file_ops_result.errors)}",
                )

        # --- Copy new files from add/ ---
        add_dir = skill_dir / "add"
        if add_dir.exists():
            for rel_path in manifest.adds:
                resolved_dest = resolve_path_remap(rel_path, path_remap)
                dest_path = project_root / resolved_dest
                if not dest_path.exists():
                    added_files.append(dest_path)
                # Copy individual file with remap (can't use copy_dir when paths differ)
                src_path = add_dir / rel_path
                if src_path.exists():
                    dest_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src_path, dest_path)

        # --- Merge modified files ---
        merge_conflicts: list[str] = []

        # Load pre-computed resolutions into git's rr-cache before merging
        applied_skill_names = [s.name for s in current_state.applied_skills]
        load_resolutions([*applied_skill_names, manifest.skill], project_root, skill_dir)

        for rel_path in manifest.modifies:
            resolved_path = resolve_path_remap(rel_path, path_remap)
            current_path = project_root / resolved_path
            base_path = project_root / G2_DIR / "base" / resolved_path
            # skill_path uses original rel_path -- skill packages are never mutated
            skill_path = skill_dir / "modify" / rel_path

            if not skill_path.exists():
                raise FileNotFoundError(f"Skill modified file not found: {skill_path}")

            if not current_path.exists():
                # File doesn't exist yet -- just copy from skill
                current_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(skill_path, current_path)
                continue

            if not base_path.exists():
                # No base -- use current as base (first-time apply)
                base_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(current_path, base_path)

            # Three-way merge: current <- base -> skill
            # Save current content before merge overwrites it (needed for rerere stage 2 = "ours")
            ours_content = current_path.read_text()
            # git merge-file modifies the first argument in-place, so use a temp copy
            tmp_current = Path(tempfile.gettempdir()) / (f"g2-merge-{uuid.uuid4()}-{Path(rel_path).name}")
            shutil.copy2(current_path, tmp_current)

            result = merge_file(tmp_current, base_path, skill_path)

            if result.clean:
                shutil.copy2(tmp_current, current_path)
                tmp_current.unlink()
            else:
                # Copy conflict markers to working tree path BEFORE rerere
                # rerere looks at the working tree file at rel_path, not at tmp_current
                shutil.copy2(tmp_current, current_path)
                tmp_current.unlink()

                if is_git_repo():
                    base_content = base_path.read_text()
                    theirs_content = skill_path.read_text()

                    setup_rerere_adapter(resolved_path, base_content, ours_content, theirs_content)
                    auto_resolved = run_rerere(str(current_path))

                    if auto_resolved:
                        # rerere resolved the conflict -- current_path now has resolved content
                        # Record the resolution: git add + git rerere
                        subprocess.run(
                            ["git", "add", resolved_path],
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
                        cleanup_merge_state(resolved_path)
                        # Unstage the file -- cleanup_merge_state clears unmerged entries
                        # but the git add above leaves the file staged at stage 0
                        with contextlib.suppress(Exception):
                            subprocess.run(
                                ["git", "restore", "--staged", resolved_path],
                                capture_output=True,
                                text=True,
                                check=False,
                            )
                        continue

                    cleanup_merge_state(resolved_path)

                # Unresolved conflict -- current_path already has conflict markers
                merge_conflicts.append(rel_path)

        if merge_conflicts:
            # Preserve backup when returning with conflicts
            return ApplyResult(
                success=False,
                skill=manifest.skill,
                version=manifest.version,
                merge_conflicts=merge_conflicts,
                backup_pending=True,
                untracked_changes=drift_files if drift_files else None,
                error=(
                    f"Merge conflicts in: {', '.join(merge_conflicts)}. "
                    "Resolve manually then run record_skill_application(). "
                    "Call clear_backup() after resolution or restore_backup() + clear_backup() to abort."
                ),
            )

        # --- Structured operations ---
        if manifest.structured and manifest.structured.get("npm_dependencies"):
            pkg_path = project_root / "package.json"
            merge_npm_dependencies(pkg_path, manifest.structured["npm_dependencies"])

        if manifest.structured and manifest.structured.get("env_additions"):
            env_path = project_root / ".env.example"
            merge_env_additions(env_path, manifest.structured["env_additions"])

        if manifest.structured and manifest.structured.get("docker_compose_services"):
            compose_path = project_root / "docker-compose.yml"
            merge_docker_compose_services(compose_path, manifest.structured["docker_compose_services"])

        # Run npm install if dependencies were added
        if (
            manifest.structured
            and manifest.structured.get("npm_dependencies")
            and len(manifest.structured["npm_dependencies"]) > 0
        ):
            run_npm_install()

        # --- Post-apply commands ---
        if manifest.post_apply and len(manifest.post_apply) > 0:
            for cmd in manifest.post_apply:
                try:
                    subprocess.run(
                        cmd,
                        shell=True,
                        capture_output=True,
                        text=True,
                        check=True,
                        cwd=project_root,
                        timeout=120,
                    )
                except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as post_err:
                    # Rollback on post_apply failure
                    for f in added_files:
                        try:
                            if f.exists():
                                f.unlink()
                        except Exception:
                            pass  # best effort
                    restore_backup()
                    clear_backup()
                    return ApplyResult(
                        success=False,
                        skill=manifest.skill,
                        version=manifest.version,
                        error=f"post_apply command failed: {cmd} — {post_err}",
                    )

        # --- Update state ---
        file_hashes: dict[str, str] = {}
        for rel_path in [*manifest.adds, *manifest.modifies]:
            resolved_path = resolve_path_remap(rel_path, path_remap)
            abs_path = project_root / resolved_path
            if abs_path.exists():
                file_hashes[resolved_path] = compute_file_hash(abs_path)

        # Store structured outcomes including the test command so apply_update() can run them
        outcomes: dict[str, object] = dict(manifest.structured) if manifest.structured else {}
        if manifest.test:
            outcomes["test"] = manifest.test

        record_skill_application(
            manifest.skill,
            manifest.version,
            file_hashes,
            outcomes if outcomes else None,
        )

        # --- Execute test command if defined ---
        if manifest.test:
            try:
                subprocess.run(
                    manifest.test,
                    shell=True,
                    capture_output=True,
                    text=True,
                    check=True,
                    cwd=project_root,
                    timeout=120,
                )
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as test_err:
                # Tests failed -- remove added files, restore backup and undo state
                for f in added_files:
                    try:
                        if f.exists():
                            f.unlink()
                    except Exception:
                        pass  # best effort
                restore_backup()
                # Re-read state and remove the skill we just recorded
                state = read_state()
                state.applied_skills = [s for s in state.applied_skills if s.name != manifest.skill]
                write_state(state)

                clear_backup()
                return ApplyResult(
                    success=False,
                    skill=manifest.skill,
                    version=manifest.version,
                    error=f"Tests failed: {test_err}",
                )

        # --- Cleanup ---
        clear_backup()

        return ApplyResult(
            success=True,
            skill=manifest.skill,
            version=manifest.version,
            untracked_changes=drift_files if drift_files else None,
        )
    except Exception:
        # Remove newly added files before restoring backup
        for f in added_files:
            try:
                if f.exists():
                    f.unlink()
            except Exception:
                pass  # best effort
        restore_backup()
        clear_backup()
        raise
    finally:
        release_lock()
