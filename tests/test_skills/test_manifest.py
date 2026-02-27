"""Tests for the manifest module (reading, validation, and compatibility checks)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import yaml

from skills_engine.manifest import (
    check_conflicts,
    check_core_version,
    check_dependencies,
    check_system_version,
    read_manifest,
)
from skills_engine.state import record_skill_application

from .conftest import create_minimal_state, create_skill_package

if TYPE_CHECKING:
    from pathlib import Path


class TestManifest:
    @pytest.fixture(autouse=True)
    def _setup(self, g2_dir: Path) -> None:
        self.tmp_dir = g2_dir
        create_minimal_state(g2_dir)

    def test_parses_valid_manifest(self) -> None:
        skill_dir = create_skill_package(
            self.tmp_dir,
            skill="telegram",
            version="2.0.0",
            core_version="1.0.0",
            adds=["src/telegram.ts"],
            modifies=["src/config.ts"],
        )
        manifest = read_manifest(skill_dir)
        assert manifest.skill == "telegram"
        assert manifest.version == "2.0.0"
        assert manifest.adds == ["src/telegram.ts"]
        assert manifest.modifies == ["src/config.ts"]

    def test_throws_on_missing_skill_field(self) -> None:
        bad_dir = self.tmp_dir / "bad-pkg"
        bad_dir.mkdir(parents=True, exist_ok=True)
        (bad_dir / "manifest.yaml").write_text(
            yaml.safe_dump(
                {
                    "version": "1.0.0",
                    "core_version": "1.0.0",
                    "adds": [],
                    "modifies": [],
                }
            )
        )
        with pytest.raises((ValueError, KeyError)):
            read_manifest(bad_dir)

    def test_throws_on_missing_version_field(self) -> None:
        bad_dir = self.tmp_dir / "bad-pkg"
        bad_dir.mkdir(parents=True, exist_ok=True)
        (bad_dir / "manifest.yaml").write_text(
            yaml.safe_dump(
                {
                    "skill": "test",
                    "core_version": "1.0.0",
                    "adds": [],
                    "modifies": [],
                }
            )
        )
        with pytest.raises((ValueError, KeyError)):
            read_manifest(bad_dir)

    def test_throws_on_missing_core_version_field(self) -> None:
        bad_dir = self.tmp_dir / "bad-pkg"
        bad_dir.mkdir(parents=True, exist_ok=True)
        (bad_dir / "manifest.yaml").write_text(
            yaml.safe_dump(
                {
                    "skill": "test",
                    "version": "1.0.0",
                    "adds": [],
                    "modifies": [],
                }
            )
        )
        with pytest.raises((ValueError, KeyError)):
            read_manifest(bad_dir)

    def test_throws_on_missing_adds_field(self) -> None:
        bad_dir = self.tmp_dir / "bad-pkg"
        bad_dir.mkdir(parents=True, exist_ok=True)
        (bad_dir / "manifest.yaml").write_text(
            yaml.safe_dump(
                {
                    "skill": "test",
                    "version": "1.0.0",
                    "core_version": "1.0.0",
                    "modifies": [],
                }
            )
        )
        with pytest.raises((ValueError, KeyError)):
            read_manifest(bad_dir)

    def test_throws_on_missing_modifies_field(self) -> None:
        bad_dir = self.tmp_dir / "bad-pkg"
        bad_dir.mkdir(parents=True, exist_ok=True)
        (bad_dir / "manifest.yaml").write_text(
            yaml.safe_dump(
                {
                    "skill": "test",
                    "version": "1.0.0",
                    "core_version": "1.0.0",
                    "adds": [],
                }
            )
        )
        with pytest.raises((ValueError, KeyError)):
            read_manifest(bad_dir)

    def test_throws_on_path_traversal_in_adds(self) -> None:
        bad_dir = self.tmp_dir / "bad-pkg"
        bad_dir.mkdir(parents=True, exist_ok=True)
        (bad_dir / "manifest.yaml").write_text(
            yaml.safe_dump(
                {
                    "skill": "test",
                    "version": "1.0.0",
                    "core_version": "1.0.0",
                    "adds": ["../etc/passwd"],
                    "modifies": [],
                }
            )
        )
        with pytest.raises(ValueError, match="Invalid path"):
            read_manifest(bad_dir)

    def test_throws_on_path_traversal_in_modifies(self) -> None:
        bad_dir = self.tmp_dir / "bad-pkg"
        bad_dir.mkdir(parents=True, exist_ok=True)
        (bad_dir / "manifest.yaml").write_text(
            yaml.safe_dump(
                {
                    "skill": "test",
                    "version": "1.0.0",
                    "core_version": "1.0.0",
                    "adds": [],
                    "modifies": ["../../secret.ts"],
                }
            )
        )
        with pytest.raises(ValueError, match="Invalid path"):
            read_manifest(bad_dir)

    def test_throws_on_absolute_path_in_adds(self) -> None:
        bad_dir = self.tmp_dir / "bad-pkg"
        bad_dir.mkdir(parents=True, exist_ok=True)
        (bad_dir / "manifest.yaml").write_text(
            yaml.safe_dump(
                {
                    "skill": "test",
                    "version": "1.0.0",
                    "core_version": "1.0.0",
                    "adds": ["/etc/passwd"],
                    "modifies": [],
                }
            )
        )
        with pytest.raises(ValueError, match="Invalid path"):
            read_manifest(bad_dir)

    def test_defaults_conflicts_and_depends_to_empty(self) -> None:
        skill_dir = create_skill_package(
            self.tmp_dir,
            skill="test",
            version="1.0.0",
            core_version="1.0.0",
            adds=[],
            modifies=[],
        )
        manifest = read_manifest(skill_dir)
        assert manifest.conflicts == []
        assert manifest.depends == []

    def test_check_core_version_returns_warning_when_manifest_targets_newer(
        self,
    ) -> None:
        skill_dir = create_skill_package(
            self.tmp_dir,
            skill="test",
            version="1.0.0",
            core_version="2.0.0",
            adds=[],
            modifies=[],
        )
        manifest = read_manifest(skill_dir)
        result = check_core_version(manifest)
        assert result["warning"]

    def test_check_core_version_returns_no_warning_when_versions_match(self) -> None:
        skill_dir = create_skill_package(
            self.tmp_dir,
            skill="test",
            version="1.0.0",
            core_version="1.0.0",
            adds=[],
            modifies=[],
        )
        manifest = read_manifest(skill_dir)
        result = check_core_version(manifest)
        assert result["ok"] is True
        assert not result.get("warning")

    def test_check_dependencies_satisfied_when_deps_present(self) -> None:
        record_skill_application("dep-skill", "1.0.0", {})
        skill_dir = create_skill_package(
            self.tmp_dir,
            skill="test",
            version="1.0.0",
            core_version="1.0.0",
            adds=[],
            modifies=[],
            depends=["dep-skill"],
        )
        manifest = read_manifest(skill_dir)
        result = check_dependencies(manifest)
        assert result["ok"] is True
        assert result["missing"] == []

    def test_check_dependencies_missing_when_deps_not_present(self) -> None:
        skill_dir = create_skill_package(
            self.tmp_dir,
            skill="test",
            version="1.0.0",
            core_version="1.0.0",
            adds=[],
            modifies=[],
            depends=["missing-skill"],
        )
        manifest = read_manifest(skill_dir)
        result = check_dependencies(manifest)
        assert result["ok"] is False
        assert "missing-skill" in result["missing"]

    def test_check_conflicts_ok_when_no_conflicts(self) -> None:
        skill_dir = create_skill_package(
            self.tmp_dir,
            skill="test",
            version="1.0.0",
            core_version="1.0.0",
            adds=[],
            modifies=[],
            conflicts=[],
        )
        manifest = read_manifest(skill_dir)
        result = check_conflicts(manifest)
        assert result["ok"] is True
        assert result["conflicting"] == []

    def test_check_conflicts_detects_conflicting_skill(self) -> None:
        record_skill_application("bad-skill", "1.0.0", {})
        skill_dir = create_skill_package(
            self.tmp_dir,
            skill="test",
            version="1.0.0",
            core_version="1.0.0",
            adds=[],
            modifies=[],
            conflicts=["bad-skill"],
        )
        manifest = read_manifest(skill_dir)
        result = check_conflicts(manifest)
        assert result["ok"] is False
        assert "bad-skill" in result["conflicting"]

    def test_parses_new_optional_fields(self) -> None:
        full_dir = self.tmp_dir / "full-pkg"
        full_dir.mkdir(parents=True, exist_ok=True)
        (full_dir / "manifest.yaml").write_text(
            yaml.safe_dump(
                {
                    "skill": "test",
                    "version": "1.0.0",
                    "core_version": "1.0.0",
                    "adds": [],
                    "modifies": [],
                    "author": "tester",
                    "license": "MIT",
                    "min_skills_system_version": "0.1.0",
                    "tested_with": ["telegram", "discord"],
                    "post_apply": ["echo done"],
                }
            )
        )
        manifest = read_manifest(full_dir)
        assert manifest.author == "tester"
        assert manifest.license == "MIT"
        assert manifest.min_skills_system_version == "0.1.0"
        assert manifest.tested_with == ["telegram", "discord"]
        assert manifest.post_apply == ["echo done"]

    def test_check_system_version_passes_when_not_set(self) -> None:
        skill_dir = create_skill_package(
            self.tmp_dir,
            skill="test",
            version="1.0.0",
            core_version="1.0.0",
            adds=[],
            modifies=[],
        )
        manifest = read_manifest(skill_dir)
        result = check_system_version(manifest)
        assert result["ok"] is True

    def test_check_system_version_passes_when_engine_is_new_enough(self) -> None:
        sys_ok_dir = self.tmp_dir / "sys-ok"
        sys_ok_dir.mkdir(parents=True, exist_ok=True)
        (sys_ok_dir / "manifest.yaml").write_text(
            yaml.safe_dump(
                {
                    "skill": "test",
                    "version": "1.0.0",
                    "core_version": "1.0.0",
                    "adds": [],
                    "modifies": [],
                    "min_skills_system_version": "0.1.0",
                }
            )
        )
        manifest = read_manifest(sys_ok_dir)
        result = check_system_version(manifest)
        assert result["ok"] is True

    def test_check_system_version_fails_when_engine_is_too_old(self) -> None:
        sys_fail_dir = self.tmp_dir / "sys-fail"
        sys_fail_dir.mkdir(parents=True, exist_ok=True)
        (sys_fail_dir / "manifest.yaml").write_text(
            yaml.safe_dump(
                {
                    "skill": "test",
                    "version": "1.0.0",
                    "core_version": "1.0.0",
                    "adds": [],
                    "modifies": [],
                    "min_skills_system_version": "99.0.0",
                }
            )
        )
        manifest = read_manifest(sys_fail_dir)
        result = check_system_version(manifest)
        assert result["ok"] is False
        assert "99.0.0" in result["error"]
