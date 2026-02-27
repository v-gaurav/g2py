"""Generate CI matrix of overlapping skill combinations.

Reads all skill manifests and computes pairs of skills that overlap
(shared modified files or shared dependencies).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from skills_engine.types import SkillManifest


@dataclass
class MatrixEntry:
    skills: list[str] = field(default_factory=list)
    reason: str = ""


@dataclass
class SkillOverlapInfo:
    name: str = ""
    modifies: list[str] = field(default_factory=list)
    npm_dependencies: list[str] = field(default_factory=list)


def extract_overlap_info(manifest: SkillManifest, dir_name: str) -> SkillOverlapInfo:
    """Extract overlap-relevant info from a parsed manifest.

    Args:
        manifest: The parsed skill manifest.
        dir_name: The skill's directory name (e.g. 'add-discord'), used in matrix
            entries so CI/scripts can locate the skill package on disk.
    """
    npm_deps: list[str] = []
    if manifest.structured and "npm_dependencies" in manifest.structured:
        npm_deps = list(manifest.structured["npm_dependencies"].keys())

    return SkillOverlapInfo(
        name=dir_name,
        modifies=manifest.modifies or [],
        npm_dependencies=npm_deps,
    )


def compute_overlap_matrix(skills: list[SkillOverlapInfo]) -> list[MatrixEntry]:
    """Compute overlap matrix from a list of skill overlap infos.

    Two skills overlap if they share any ``modifies`` entry or both declare
    ``structured.npm_dependencies`` for the same package.
    """
    entries: list[MatrixEntry] = []

    for i in range(len(skills)):
        for j in range(i + 1, len(skills)):
            a = skills[i]
            b = skills[j]
            reasons: list[str] = []

            # Check shared modifies entries
            shared_modifies = [m for m in a.modifies if m in b.modifies]
            if shared_modifies:
                reasons.append(f"shared modifies: {', '.join(shared_modifies)}")

            # Check shared npm_dependencies packages
            shared_npm = [pkg for pkg in a.npm_dependencies if pkg in b.npm_dependencies]
            if shared_npm:
                reasons.append(f"shared npm packages: {', '.join(shared_npm)}")

            if reasons:
                entries.append(
                    MatrixEntry(
                        skills=[a.name, b.name],
                        reason="; ".join(reasons),
                    )
                )

    return entries


def read_all_manifests(
    skills_dir: Path,
) -> list[tuple[SkillManifest, str]]:
    """Read all skill manifests from a skills directory (e.g. .claude/skills/).

    Each subdirectory should contain a manifest.yaml.
    Returns both the parsed manifest and the directory name.
    """
    if not skills_dir.exists():
        return []

    results: list[tuple[SkillManifest, str]] = []

    for entry in sorted(skills_dir.iterdir()):
        if not entry.is_dir():
            continue

        manifest_path = entry / "manifest.yaml"
        if not manifest_path.exists():
            continue

        content = manifest_path.read_text(encoding="utf-8")
        data = yaml.safe_load(content)
        manifest = SkillManifest(**data)
        results.append((manifest, entry.name))

    return results


def generate_matrix(skills_dir: Path) -> list[MatrixEntry]:
    """Generate the full CI matrix from a skills directory."""
    entries = read_all_manifests(skills_dir)
    overlap_infos = [extract_overlap_info(m, d) for m, d in entries]
    return compute_overlap_matrix(overlap_infos)


def main() -> None:
    project_root = Path.cwd()
    skills_dir = project_root / ".claude" / "skills"
    matrix = generate_matrix(skills_dir)
    serializable = [{"skills": e.skills, "reason": e.reason} for e in matrix]
    print(json.dumps(serializable, indent=2))


if __name__ == "__main__":
    main()
