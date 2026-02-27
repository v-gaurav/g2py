"""Replay skills from clean base state."""

from __future__ import annotations

import contextlib
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from .constants import BASE_DIR
from .file_ops import execute_file_ops
from .manifest import read_manifest
from .merge import (
    cleanup_merge_state,
    is_git_repo,
    merge_file,
    run_rerere,
    setup_rerere_adapter,
)
from .path_remap import load_path_remap, resolve_path_remap
from .resolution_cache import load_resolutions
from .structured import (
    merge_docker_compose_services,
    merge_env_additions,
    merge_npm_dependencies,
    run_npm_install,
)


class ReplayResult(BaseModel):
    """Result of replaying skills."""

    success: bool
    per_skill: dict[str, dict[str, Any]]
    merge_conflicts: list[str] | None = None
    error: str | None = None


def find_skill_dir(skill_name: str, project_root: Path | None = None) -> Path | None:
    """Scan .claude/skills/ for a directory whose manifest.yaml has skill: <skill_name>."""
    root = project_root or Path.cwd()
    skills_root = root / ".claude" / "skills"
    if not skills_root.exists():
        return None

    for entry in skills_root.iterdir():
        if not entry.is_dir():
            continue
        manifest_path = entry / "manifest.yaml"
        if not manifest_path.exists():
            continue

        try:
            manifest = read_manifest(entry)
            if manifest.skill == skill_name:
                return entry
        except Exception:
            # Skip invalid manifests
            pass

    return None


def replay_skills(
    skills: list[str],
    skill_dirs: dict[str, Path],
    project_root: Path | None = None,
) -> ReplayResult:
    """Replay a list of skills from clean base state.

    Used by uninstall (replay-without) and rebase.
    """
    project_root = project_root or Path.cwd()
    base_dir = project_root / BASE_DIR
    path_remap = load_path_remap()

    per_skill: dict[str, dict[str, Any]] = {}
    all_merge_conflicts: list[str] = []

    # 1. Collect all files touched by any skill in the list
    all_touched_files: set[str] = set()
    for skill_name in skills:
        skill_dir = skill_dirs.get(skill_name)
        if not skill_dir:
            per_skill[skill_name] = {
                "success": False,
                "error": f"Skill directory not found for: {skill_name}",
            }
            return ReplayResult(
                success=False,
                per_skill=per_skill,
                error=f"Missing skill directory for: {skill_name}",
            )

        manifest = read_manifest(skill_dir)
        for f in manifest.adds:
            all_touched_files.add(f)
        for f in manifest.modifies:
            all_touched_files.add(f)

    # 2. Reset touched files to clean base
    for rel_path in all_touched_files:
        resolved_path = resolve_path_remap(rel_path, path_remap)
        current_path = project_root / resolved_path
        base_path = base_dir / resolved_path

        if base_path.exists():
            # Restore from base
            current_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(base_path, current_path)
        elif current_path.exists():
            # Add-only file not in base -- remove it
            current_path.unlink()

    # 3. Load pre-computed resolutions into git's rr-cache before replaying
    # Pass the last skill's dir -- it's the one applied on top, producing conflicts
    last_skill_dir = skill_dirs[skills[-1]] if skills else None
    load_resolutions(skills, project_root, last_skill_dir)

    # Replay each skill in order
    # Collect structured ops for batch application
    all_npm_deps: dict[str, str] = {}
    all_env_additions: list[str] = []
    all_docker_services: dict[str, Any] = {}
    has_npm_deps = False

    for skill_name in skills:
        skill_dir = skill_dirs[skill_name]
        try:
            manifest = read_manifest(skill_dir)

            # Execute file_ops
            if manifest.file_ops and len(manifest.file_ops) > 0:
                file_ops_result = execute_file_ops(manifest.file_ops, project_root)
                if not file_ops_result.success:
                    per_skill[skill_name] = {
                        "success": False,
                        "error": f"File operations failed: {'; '.join(file_ops_result.errors)}",
                    }
                    return ReplayResult(
                        success=False,
                        per_skill=per_skill,
                        error=f"File ops failed for {skill_name}",
                    )

            # Copy add/ files
            add_dir = skill_dir / "add"
            if add_dir.exists():
                for rel_path in manifest.adds:
                    resolved_dest = resolve_path_remap(rel_path, path_remap)
                    dest_path = project_root / resolved_dest
                    src_path = add_dir / rel_path
                    if src_path.exists():
                        dest_path.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(src_path, dest_path)

            # Three-way merge modify/ files
            skill_conflicts: list[str] = []

            for rel_path in manifest.modifies:
                resolved_path = resolve_path_remap(rel_path, path_remap)
                current_path = project_root / resolved_path
                base_path = base_dir / resolved_path
                skill_path = skill_dir / "modify" / rel_path

                if not skill_path.exists():
                    skill_conflicts.append(rel_path)
                    continue

                if not current_path.exists():
                    current_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(skill_path, current_path)
                    continue

                if not base_path.exists():
                    base_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(current_path, base_path)

                ours_content = current_path.read_text()
                tmp_current = Path(tempfile.gettempdir()) / (f"g2-replay-{uuid.uuid4()}-{Path(rel_path).name}")
                shutil.copy2(current_path, tmp_current)

                result = merge_file(tmp_current, base_path, skill_path)

                if result.clean:
                    shutil.copy2(tmp_current, current_path)
                    tmp_current.unlink()
                else:
                    shutil.copy2(tmp_current, current_path)
                    tmp_current.unlink()

                    if is_git_repo():
                        base_content = base_path.read_text()
                        theirs_content = skill_path.read_text()

                        setup_rerere_adapter(
                            resolved_path,
                            base_content,
                            ours_content,
                            theirs_content,
                        )
                        auto_resolved = run_rerere(str(current_path))

                        if auto_resolved:
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
                            continue

                        cleanup_merge_state(resolved_path)

                    skill_conflicts.append(resolved_path)

            if skill_conflicts:
                all_merge_conflicts.extend(skill_conflicts)
                per_skill[skill_name] = {
                    "success": False,
                    "error": f"Merge conflicts: {', '.join(skill_conflicts)}",
                }
                # Stop on first conflict -- later skills would merge against conflict markers
                break
            else:
                per_skill[skill_name] = {"success": True}

            # Collect structured ops
            if manifest.structured and manifest.structured.get("npm_dependencies"):
                all_npm_deps.update(manifest.structured["npm_dependencies"])
                has_npm_deps = True
            if manifest.structured and manifest.structured.get("env_additions"):
                all_env_additions.extend(manifest.structured["env_additions"])
            if manifest.structured and manifest.structured.get("docker_compose_services"):
                all_docker_services.update(manifest.structured["docker_compose_services"])
        except Exception as err:
            per_skill[skill_name] = {
                "success": False,
                "error": str(err),
            }
            return ReplayResult(
                success=False,
                per_skill=per_skill,
                error=f"Replay failed for {skill_name}: {err}",
            )

    if all_merge_conflicts:
        return ReplayResult(
            success=False,
            per_skill=per_skill,
            merge_conflicts=all_merge_conflicts,
            error=f"Unresolved merge conflicts: {', '.join(all_merge_conflicts)}",
        )

    # 4. Apply aggregated structured operations (only if no conflicts)
    if has_npm_deps:
        pkg_path = project_root / "package.json"
        merge_npm_dependencies(pkg_path, all_npm_deps)

    if all_env_additions:
        env_path = project_root / ".env.example"
        merge_env_additions(env_path, all_env_additions)

    if all_docker_services:
        compose_path = project_root / "docker-compose.yml"
        merge_docker_compose_services(compose_path, all_docker_services)

    # 5. Run npm install if any deps
    if has_npm_deps:
        with contextlib.suppress(Exception):
            run_npm_install()

    return ReplayResult(success=True, per_skill=per_skill)
