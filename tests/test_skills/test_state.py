"""Tests for the state module (read, write, record, hash, semver)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from skills_engine.state import (
    compare_semver,
    compute_file_hash,
    get_custom_modifications,
    read_state,
    record_custom_modification,
    record_skill_application,
    write_state,
)
from skills_engine.types import SkillState

from .conftest import create_minimal_state
from .conftest import write_state as write_state_helper

if TYPE_CHECKING:
    from pathlib import Path


class TestState:
    @pytest.fixture(autouse=True)
    def _setup(self, g2_dir: Path) -> None:
        self.tmp_dir = g2_dir

    def test_read_write_roundtrip(self) -> None:
        state = SkillState(
            skills_system_version="0.1.0",
            core_version="1.0.0",
            applied_skills=[],
        )
        write_state(state)
        result = read_state()
        assert result.skills_system_version == "0.1.0"
        assert result.core_version == "1.0.0"
        assert result.applied_skills == []

    def test_read_state_throws_when_no_state_file(self) -> None:
        with pytest.raises(FileNotFoundError):
            read_state()

    def test_read_state_throws_when_version_newer_than_current(self) -> None:
        write_state_helper(
            self.tmp_dir,
            {
                "skills_system_version": "99.0.0",
                "core_version": "1.0.0",
                "applied_skills": [],
            },
        )
        with pytest.raises(RuntimeError):
            read_state()

    def test_record_skill_application_adds_a_skill(self) -> None:
        create_minimal_state(self.tmp_dir)
        record_skill_application("my-skill", "1.0.0", {"src/foo.ts": "abc123"})
        state = read_state()
        assert len(state.applied_skills) == 1
        assert state.applied_skills[0].name == "my-skill"
        assert state.applied_skills[0].version == "1.0.0"
        assert state.applied_skills[0].file_hashes == {"src/foo.ts": "abc123"}

    def test_re_applying_same_skill_replaces_it(self) -> None:
        create_minimal_state(self.tmp_dir)
        record_skill_application("my-skill", "1.0.0", {"a.ts": "hash1"})
        record_skill_application("my-skill", "2.0.0", {"a.ts": "hash2"})
        state = read_state()
        assert len(state.applied_skills) == 1
        assert state.applied_skills[0].version == "2.0.0"
        assert state.applied_skills[0].file_hashes == {"a.ts": "hash2"}

    def test_compute_file_hash_produces_consistent_sha256(self) -> None:
        file_path = self.tmp_dir / "hashtest.txt"
        file_path.write_text("hello world")
        hash1 = compute_file_hash(file_path)
        hash2 = compute_file_hash(file_path)
        assert hash1 == hash2
        # SHA-256 produces 64 hex characters
        assert len(hash1) == 64
        assert all(c in "0123456789abcdef" for c in hash1)


class TestCompareSemver:
    def test_1_0_0_less_than_1_1_0(self) -> None:
        assert compare_semver("1.0.0", "1.1.0") < 0

    def test_0_9_0_less_than_0_10_0(self) -> None:
        assert compare_semver("0.9.0", "0.10.0") < 0

    def test_equal_versions(self) -> None:
        assert compare_semver("1.0.0", "1.0.0") == 0


class TestCustomModifications:
    @pytest.fixture(autouse=True)
    def _setup_state(self, g2_dir: Path) -> None:
        self.tmp_dir = g2_dir
        create_minimal_state(g2_dir)

    def test_record_custom_modification_adds_to_array(self) -> None:
        record_custom_modification("tweak", ["src/a.ts"], "custom/001-tweak.patch")
        mods = get_custom_modifications()
        assert len(mods) == 1
        assert mods[0].description == "tweak"
        assert mods[0].files_modified == ["src/a.ts"]
        assert mods[0].patch_file == "custom/001-tweak.patch"

    def test_get_custom_modifications_returns_empty_when_none(self) -> None:
        mods = get_custom_modifications()
        assert mods == []
