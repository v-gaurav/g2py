"""Tests for the CI matrix generation module (overlap detection, matrix generation)."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

# The ci_matrix module lives outside the g2 package, in scripts/
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from generate_ci_matrix import (  # noqa: E402
    SkillOverlapInfo,
    compute_overlap_matrix,
    extract_overlap_info,
    generate_matrix,
)

from skills_engine.types import SkillManifest


def _make_manifest(overrides: dict[str, Any]) -> SkillManifest:
    defaults: dict[str, Any] = {
        "version": "1.0.0",
        "description": "Test skill",
        "core_version": "1.0.0",
        "adds": [],
        "modifies": [],
        "conflicts": [],
        "depends": [],
    }
    defaults.update(overrides)
    return SkillManifest(**defaults)


class TestComputeOverlapMatrix:
    def test_detects_overlap_from_shared_modifies(self) -> None:
        skills = [
            SkillOverlapInfo(
                name="telegram",
                modifies=["src/config.ts", "src/index.ts"],
                npm_dependencies=[],
            ),
            SkillOverlapInfo(
                name="discord",
                modifies=["src/config.ts", "src/router.ts"],
                npm_dependencies=[],
            ),
        ]

        matrix = compute_overlap_matrix(skills)

        assert len(matrix) == 1
        assert matrix[0].skills == ["telegram", "discord"]
        assert "shared modifies" in matrix[0].reason
        assert "src/config.ts" in matrix[0].reason

    def test_returns_no_entry_for_non_overlapping_skills(self) -> None:
        skills = [
            SkillOverlapInfo(
                name="telegram",
                modifies=["src/telegram.ts"],
                npm_dependencies=["grammy"],
            ),
            SkillOverlapInfo(
                name="discord",
                modifies=["src/discord.ts"],
                npm_dependencies=["discord.js"],
            ),
        ]

        matrix = compute_overlap_matrix(skills)
        assert len(matrix) == 0

    def test_detects_overlap_from_shared_npm_dependencies(self) -> None:
        skills = [
            SkillOverlapInfo(
                name="skill-a",
                modifies=["src/a.ts"],
                npm_dependencies=["lodash", "zod"],
            ),
            SkillOverlapInfo(
                name="skill-b",
                modifies=["src/b.ts"],
                npm_dependencies=["zod", "express"],
            ),
        ]

        matrix = compute_overlap_matrix(skills)

        assert len(matrix) == 1
        assert matrix[0].skills == ["skill-a", "skill-b"]
        assert "shared npm packages" in matrix[0].reason
        assert "zod" in matrix[0].reason

    def test_reports_both_modifies_and_npm_overlap_in_one_entry(self) -> None:
        skills = [
            SkillOverlapInfo(
                name="skill-a",
                modifies=["src/config.ts"],
                npm_dependencies=["zod"],
            ),
            SkillOverlapInfo(
                name="skill-b",
                modifies=["src/config.ts"],
                npm_dependencies=["zod"],
            ),
        ]

        matrix = compute_overlap_matrix(skills)

        assert len(matrix) == 1
        assert "shared modifies" in matrix[0].reason
        assert "shared npm packages" in matrix[0].reason

    def test_handles_three_skills_with_pairwise_overlaps(self) -> None:
        skills = [
            SkillOverlapInfo(
                name="a",
                modifies=["src/config.ts"],
                npm_dependencies=[],
            ),
            SkillOverlapInfo(
                name="b",
                modifies=["src/config.ts", "src/router.ts"],
                npm_dependencies=[],
            ),
            SkillOverlapInfo(
                name="c",
                modifies=["src/router.ts"],
                npm_dependencies=[],
            ),
        ]

        matrix = compute_overlap_matrix(skills)

        # a-b overlap on config.ts, b-c overlap on router.ts, a-c no overlap
        assert len(matrix) == 2
        assert matrix[0].skills == ["a", "b"]
        assert matrix[1].skills == ["b", "c"]

    def test_returns_empty_array_for_single_skill(self) -> None:
        skills = [
            SkillOverlapInfo(
                name="only",
                modifies=["src/config.ts"],
                npm_dependencies=["zod"],
            ),
        ]

        matrix = compute_overlap_matrix(skills)
        assert len(matrix) == 0

    def test_returns_empty_array_for_no_skills(self) -> None:
        matrix = compute_overlap_matrix([])
        assert len(matrix) == 0


class TestExtractOverlapInfo:
    def test_extracts_modifies_and_npm_dependencies_using_dir_name(self) -> None:
        manifest = _make_manifest(
            {
                "skill": "telegram",
                "modifies": ["src/config.ts"],
                "structured": {
                    "npm_dependencies": {"grammy": "^1.0.0", "zod": "^3.0.0"},
                },
            }
        )

        info = extract_overlap_info(manifest, "add-telegram")

        assert info.name == "add-telegram"
        assert info.modifies == ["src/config.ts"]
        assert info.npm_dependencies == ["grammy", "zod"]

    def test_handles_manifest_without_structured_field(self) -> None:
        manifest = _make_manifest(
            {
                "skill": "simple",
                "modifies": ["src/index.ts"],
            }
        )

        info = extract_overlap_info(manifest, "add-simple")
        assert info.npm_dependencies == []

    def test_handles_structured_without_npm_dependencies(self) -> None:
        manifest = _make_manifest(
            {
                "skill": "env-only",
                "modifies": [],
                "structured": {
                    "env_additions": ["MY_VAR"],
                },
            }
        )

        info = extract_overlap_info(manifest, "add-env-only")
        assert info.npm_dependencies == []


class TestGenerateMatrixWithFilesystem:
    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path: Path) -> None:
        self.tmp_dir = tmp_path

    @staticmethod
    def _create_manifest_dir(skills_dir: Path, name: str, manifest: dict[str, Any]) -> None:
        d = skills_dir / name
        d.mkdir(parents=True, exist_ok=True)
        (d / "manifest.yaml").write_text(yaml.safe_dump(manifest))

    def test_reads_manifests_from_disk_and_finds_overlaps(self) -> None:
        skills_dir = self.tmp_dir / ".claude" / "skills"

        self._create_manifest_dir(
            skills_dir,
            "telegram",
            {
                "skill": "telegram",
                "version": "1.0.0",
                "core_version": "1.0.0",
                "adds": ["src/telegram.ts"],
                "modifies": ["src/config.ts", "src/index.ts"],
                "conflicts": [],
                "depends": [],
            },
        )

        self._create_manifest_dir(
            skills_dir,
            "discord",
            {
                "skill": "discord",
                "version": "1.0.0",
                "core_version": "1.0.0",
                "adds": ["src/discord.ts"],
                "modifies": ["src/config.ts", "src/index.ts"],
                "conflicts": [],
                "depends": [],
            },
        )

        matrix = generate_matrix(skills_dir)

        assert len(matrix) == 1
        assert "telegram" in matrix[0].skills
        assert "discord" in matrix[0].skills

    def test_returns_empty_matrix_when_skills_dir_does_not_exist(self) -> None:
        matrix = generate_matrix(self.tmp_dir / "nonexistent")
        assert len(matrix) == 0

    def test_returns_empty_matrix_for_non_overlapping_skills_on_disk(self) -> None:
        skills_dir = self.tmp_dir / ".claude" / "skills"

        self._create_manifest_dir(
            skills_dir,
            "alpha",
            {
                "skill": "alpha",
                "version": "1.0.0",
                "core_version": "1.0.0",
                "adds": ["src/alpha.ts"],
                "modifies": ["src/alpha-config.ts"],
                "conflicts": [],
                "depends": [],
            },
        )

        self._create_manifest_dir(
            skills_dir,
            "beta",
            {
                "skill": "beta",
                "version": "1.0.0",
                "core_version": "1.0.0",
                "adds": ["src/beta.ts"],
                "modifies": ["src/beta-config.ts"],
                "conflicts": [],
                "depends": [],
            },
        )

        matrix = generate_matrix(skills_dir)
        assert len(matrix) == 0

    def test_detects_structured_npm_overlap_from_disk_manifests(self) -> None:
        skills_dir = self.tmp_dir / ".claude" / "skills"

        self._create_manifest_dir(
            skills_dir,
            "skill-x",
            {
                "skill": "skill-x",
                "version": "1.0.0",
                "core_version": "1.0.0",
                "adds": [],
                "modifies": ["src/x.ts"],
                "conflicts": [],
                "depends": [],
                "structured": {
                    "npm_dependencies": {"lodash": "^4.0.0"},
                },
            },
        )

        self._create_manifest_dir(
            skills_dir,
            "skill-y",
            {
                "skill": "skill-y",
                "version": "1.0.0",
                "core_version": "1.0.0",
                "adds": [],
                "modifies": ["src/y.ts"],
                "conflicts": [],
                "depends": [],
                "structured": {
                    "npm_dependencies": {"lodash": "^4.1.0"},
                },
            },
        )

        matrix = generate_matrix(skills_dir)

        assert len(matrix) == 1
        assert "lodash" in matrix[0].reason
