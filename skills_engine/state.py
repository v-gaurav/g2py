"""Skills state persistence and file hashing."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import yaml

from .constants import G2_DIR, SKILLS_SCHEMA_VERSION, STATE_FILE
from .types import AppliedSkill, CustomModification, SkillState


def _get_state_path() -> Path:
    return Path.cwd() / G2_DIR / STATE_FILE


def read_state() -> SkillState:
    """Read and validate the skills state file."""
    state_path = _get_state_path()
    if not state_path.exists():
        raise FileNotFoundError(".g2/state.yaml not found. Run init_skills_system() first.")

    content = state_path.read_text(encoding="utf-8")
    raw = yaml.safe_load(content)
    state = SkillState(**raw)

    if compare_semver(state.skills_system_version, SKILLS_SCHEMA_VERSION) > 0:
        raise RuntimeError(
            f"state.yaml version {state.skills_system_version} is newer than "
            f"tooling version {SKILLS_SCHEMA_VERSION}. Update your skills engine."
        )

    return state


def write_state(state: SkillState) -> None:
    """Atomically write the skills state file."""
    state_path = _get_state_path()
    state_path.parent.mkdir(parents=True, exist_ok=True)

    content = yaml.safe_dump(state.model_dump(exclude_none=True), sort_keys=True)

    # Write to temp file then atomic rename to prevent corruption on crash
    tmp_path = state_path.with_suffix(".yaml.tmp")
    tmp_path.write_text(content, encoding="utf-8")
    tmp_path.rename(state_path)


def record_skill_application(
    skill_name: str,
    version: str,
    file_hashes: dict[str, str],
    structured_outcomes: dict[str, object] | None = None,
) -> None:
    """Record a skill application in state, replacing any previous entry."""
    state = read_state()

    # Remove previous application of same skill if exists
    state.applied_skills = [s for s in state.applied_skills if s.name != skill_name]

    state.applied_skills.append(
        AppliedSkill(
            name=skill_name,
            version=version,
            applied_at=datetime.now(UTC).isoformat(),
            file_hashes=file_hashes,
            structured_outcomes=structured_outcomes,
        )
    )

    write_state(state)


def get_applied_skills() -> list[AppliedSkill]:
    """Return the list of currently applied skills."""
    state = read_state()
    return state.applied_skills


def record_custom_modification(
    description: str,
    files_modified: list[str],
    patch_file: str,
) -> None:
    """Record a custom modification in state."""
    state = read_state()

    if state.custom_modifications is None:
        state.custom_modifications = []

    mod = CustomModification(
        description=description,
        applied_at=datetime.now(UTC).isoformat(),
        files_modified=files_modified,
        patch_file=patch_file,
    )

    state.custom_modifications.append(mod)
    write_state(state)


def get_custom_modifications() -> list[CustomModification]:
    """Return the list of custom modifications."""
    state = read_state()
    return state.custom_modifications or []


def compute_file_hash(file_path: Path) -> str:
    """Compute the SHA-256 hash of a file's contents."""
    content = file_path.read_bytes()
    return hashlib.sha256(content).hexdigest()


def compare_semver(a: str, b: str) -> int:
    """Compare two semver strings.

    Returns negative if a < b, 0 if equal, positive if a > b.
    """
    parts_a = [int(x) for x in a.split(".")]
    parts_b = [int(x) for x in b.split(".")]

    for i in range(max(len(parts_a), len(parts_b))):
        val_a = parts_a[i] if i < len(parts_a) else 0
        val_b = parts_b[i] if i < len(parts_b) else 0
        diff = val_a - val_b
        if diff != 0:
            return diff

    return 0
