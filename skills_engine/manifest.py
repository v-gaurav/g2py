"""Skill manifest reading, validation, and compatibility checks."""

from __future__ import annotations

from pathlib import Path, PurePosixPath

import yaml

from .constants import SKILLS_SCHEMA_VERSION
from .state import compare_semver, get_applied_skills, read_state
from .types import SkillManifest


def read_manifest(skill_dir: Path) -> SkillManifest:
    """Read and validate a skill manifest from a directory."""
    manifest_path = skill_dir / "manifest.yaml"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Manifest not found: {manifest_path}")

    content = manifest_path.read_text()
    raw = yaml.safe_load(content)

    # Validate required fields
    required = ["skill", "version", "core_version", "adds", "modifies"]
    for field in required:
        if raw.get(field) is None:
            raise ValueError(f"Manifest missing required field: {field}")

    # Validate paths don't escape project root (before model_validate so path
    # traversal errors are surfaced even when optional fields are missing)
    all_paths = [*(raw.get("adds") or []), *(raw.get("modifies") or [])]
    for p in all_paths:
        if ".." in p or PurePosixPath(p).is_absolute():
            raise ValueError(f'Invalid path in manifest: {p} (must be relative without "..")')

    # Apply defaults
    raw.setdefault("conflicts", [])
    raw.setdefault("depends", [])
    raw.setdefault("file_ops", [])

    manifest = SkillManifest.model_validate(raw)

    return manifest


def check_core_version(manifest: SkillManifest) -> dict[str, str | bool]:
    """Check if manifest core_version is compatible with current state."""
    state = read_state()
    cmp = compare_semver(manifest.core_version, state.core_version)
    if cmp > 0:
        return {
            "ok": True,
            "warning": (
                f"Skill targets core {manifest.core_version} but current core "
                f"is {state.core_version}. The merge might still work but "
                f"there's a compatibility risk."
            ),
        }
    return {"ok": True}


def check_dependencies(manifest: SkillManifest) -> dict[str, bool | list[str]]:
    """Check if all skill dependencies are already applied."""
    applied = get_applied_skills()
    applied_names = {s.name for s in applied}
    missing = [dep for dep in manifest.depends if dep not in applied_names]
    return {"ok": len(missing) == 0, "missing": missing}


def check_system_version(manifest: SkillManifest) -> dict[str, bool | str]:
    """Check if the skill's min_skills_system_version is satisfied."""
    if not manifest.min_skills_system_version:
        return {"ok": True}
    cmp = compare_semver(manifest.min_skills_system_version, SKILLS_SCHEMA_VERSION)
    if cmp > 0:
        return {
            "ok": False,
            "error": (
                f"Skill requires skills system version "
                f"{manifest.min_skills_system_version} but current is "
                f"{SKILLS_SCHEMA_VERSION}. Update your skills engine."
            ),
        }
    return {"ok": True}


def check_conflicts(manifest: SkillManifest) -> dict[str, bool | list[str]]:
    """Check if any conflicting skills are already applied."""
    applied = get_applied_skills()
    applied_names = {s.name for s in applied}
    conflicting = [c for c in manifest.conflicts if c in applied_names]
    return {"ok": len(conflicting) == 0, "conflicting": conflicting}
