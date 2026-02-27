"""Tests for the replay module (finding skill dirs, replaying skills from base)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import yaml

from skills_engine.replay import find_skill_dir, replay_skills

from .conftest import (
    create_minimal_state,
    create_skill_package,
    init_git_repo,
)

if TYPE_CHECKING:
    from pathlib import Path


class TestFindSkillDir:
    @pytest.fixture(autouse=True)
    def _setup(self, g2_dir: Path) -> None:
        self.tmp_dir = g2_dir
        create_minimal_state(g2_dir)
        init_git_repo(g2_dir)

    def test_finds_skill_directory_by_name(self) -> None:
        skills_root = self.tmp_dir / ".claude" / "skills" / "telegram"
        skills_root.mkdir(parents=True, exist_ok=True)
        (skills_root / "manifest.yaml").write_text(
            yaml.safe_dump(
                {
                    "skill": "telegram",
                    "version": "1.0.0",
                    "core_version": "1.0.0",
                    "adds": [],
                    "modifies": [],
                }
            )
        )

        result = find_skill_dir("telegram", self.tmp_dir)
        assert result == skills_root

    def test_returns_none_for_missing_skill(self) -> None:
        result = find_skill_dir("nonexistent", self.tmp_dir)
        assert result is None

    def test_returns_none_when_skills_dir_does_not_exist(self) -> None:
        result = find_skill_dir("anything", self.tmp_dir)
        assert result is None


class TestReplaySkills:
    @pytest.fixture(autouse=True)
    def _setup(self, g2_dir: Path) -> None:
        self.tmp_dir = g2_dir
        create_minimal_state(g2_dir)
        init_git_repo(g2_dir)

    def test_replays_single_skill_from_base(self) -> None:
        # Set up base file
        base_dir = self.tmp_dir / ".g2" / "base" / "src"
        base_dir.mkdir(parents=True, exist_ok=True)
        (base_dir / "config.ts").write_text("base content\n")

        # Set up current file (will be overwritten by replay)
        (self.tmp_dir / "src").mkdir(parents=True, exist_ok=True)
        (self.tmp_dir / "src" / "config.ts").write_text("modified content\n")

        # Create skill package
        skill_dir = create_skill_package(
            self.tmp_dir,
            skill="telegram",
            version="1.0.0",
            core_version="1.0.0",
            adds=["src/telegram.ts"],
            modifies=["src/config.ts"],
            add_files={"src/telegram.ts": "telegram code\n"},
            modify_files={"src/config.ts": "base content\ntelegram config\n"},
        )

        result = replay_skills(
            skills=["telegram"],
            skill_dirs={"telegram": skill_dir},
            project_root=self.tmp_dir,
        )

        assert result.success is True
        assert result.per_skill["telegram"]["success"] is True

        # Added file should exist
        assert (self.tmp_dir / "src" / "telegram.ts").exists()
        assert (self.tmp_dir / "src" / "telegram.ts").read_text() == "telegram code\n"

        # Modified file should be merged from base
        config = (self.tmp_dir / "src" / "config.ts").read_text()
        assert "telegram config" in config

    def test_replays_two_skills_in_order(self) -> None:
        # Set up base
        base_dir = self.tmp_dir / ".g2" / "base" / "src"
        base_dir.mkdir(parents=True, exist_ok=True)
        (base_dir / "config.ts").write_text("line1\nline2\nline3\nline4\nline5\n")

        (self.tmp_dir / "src").mkdir(parents=True, exist_ok=True)
        (self.tmp_dir / "src" / "config.ts").write_text("line1\nline2\nline3\nline4\nline5\n")

        # Skill 1 adds at top
        skill1_dir = create_skill_package(
            self.tmp_dir,
            skill="telegram",
            version="1.0.0",
            core_version="1.0.0",
            adds=["src/telegram.ts"],
            modifies=["src/config.ts"],
            add_files={"src/telegram.ts": "tg code"},
            modify_files={
                "src/config.ts": "telegram import\nline1\nline2\nline3\nline4\nline5\n",
            },
            dir_name="skill-pkg-tg",
        )

        # Skill 2 adds at bottom
        skill2_dir = create_skill_package(
            self.tmp_dir,
            skill="discord",
            version="1.0.0",
            core_version="1.0.0",
            adds=["src/discord.ts"],
            modifies=["src/config.ts"],
            add_files={"src/discord.ts": "dc code"},
            modify_files={
                "src/config.ts": "line1\nline2\nline3\nline4\nline5\ndiscord import\n",
            },
            dir_name="skill-pkg-dc",
        )

        result = replay_skills(
            skills=["telegram", "discord"],
            skill_dirs={"telegram": skill1_dir, "discord": skill2_dir},
            project_root=self.tmp_dir,
        )

        assert result.success is True
        assert result.per_skill["telegram"]["success"] is True
        assert result.per_skill["discord"]["success"] is True

        # Both added files should exist
        assert (self.tmp_dir / "src" / "telegram.ts").exists()
        assert (self.tmp_dir / "src" / "discord.ts").exists()

        # Config should have both changes
        config = (self.tmp_dir / "src" / "config.ts").read_text()
        assert "telegram import" in config
        assert "discord import" in config

    def test_stops_on_first_conflict(self) -> None:
        base_dir = self.tmp_dir / ".g2" / "base" / "src"
        base_dir.mkdir(parents=True, exist_ok=True)
        (base_dir / "config.ts").write_text("line1\n")

        (self.tmp_dir / "src").mkdir(parents=True, exist_ok=True)
        (self.tmp_dir / "src" / "config.ts").write_text("line1\n")

        # Skill 1: changes line 1 -- merges cleanly since current=base after reset
        skill1_dir = create_skill_package(
            self.tmp_dir,
            skill="skill-a",
            version="1.0.0",
            core_version="1.0.0",
            adds=[],
            modifies=["src/config.ts"],
            modify_files={"src/config.ts": "line1-from-skill-a\n"},
            dir_name="skill-pkg-a",
        )

        # Skill 2: also changes line 1 differently -- conflict with skill-a's result
        skill2_dir = create_skill_package(
            self.tmp_dir,
            skill="skill-b",
            version="1.0.0",
            core_version="1.0.0",
            adds=[],
            modifies=["src/config.ts"],
            modify_files={"src/config.ts": "line1-from-skill-b\n"},
            dir_name="skill-pkg-b",
        )

        # Skill 3: adds a new file -- should be skipped
        skill3_dir = create_skill_package(
            self.tmp_dir,
            skill="skill-c",
            version="1.0.0",
            core_version="1.0.0",
            adds=["src/newfile.ts"],
            modifies=[],
            add_files={"src/newfile.ts": "should not appear"},
            dir_name="skill-pkg-c",
        )

        result = replay_skills(
            skills=["skill-a", "skill-b", "skill-c"],
            skill_dirs={
                "skill-a": skill1_dir,
                "skill-b": skill2_dir,
                "skill-c": skill3_dir,
            },
            project_root=self.tmp_dir,
        )

        assert result.success is False
        assert result.merge_conflicts is not None
        assert len(result.merge_conflicts) > 0
        # Skill B caused the conflict
        assert result.per_skill["skill-b"]["success"] is False
        # Skill C should NOT have been processed
        assert "skill-c" not in result.per_skill

    def test_returns_error_for_missing_skill_dir(self) -> None:
        result = replay_skills(
            skills=["missing"],
            skill_dirs={},
            project_root=self.tmp_dir,
        )

        assert result.success is False
        assert "missing" in result.error
        assert result.per_skill["missing"]["success"] is False

    def test_resets_files_to_base_before_replay(self) -> None:
        # Set up base
        base_dir = self.tmp_dir / ".g2" / "base" / "src"
        base_dir.mkdir(parents=True, exist_ok=True)
        (base_dir / "config.ts").write_text("base content\n")

        # Current has drift
        (self.tmp_dir / "src").mkdir(parents=True, exist_ok=True)
        (self.tmp_dir / "src" / "config.ts").write_text("drifted content\n")

        # Also a stale added file
        (self.tmp_dir / "src" / "stale-add.ts").write_text("should be removed")

        skill_dir = create_skill_package(
            self.tmp_dir,
            skill="skill1",
            version="1.0.0",
            core_version="1.0.0",
            adds=["src/stale-add.ts"],
            modifies=["src/config.ts"],
            add_files={"src/stale-add.ts": "fresh add"},
            modify_files={"src/config.ts": "base content\nskill addition\n"},
        )

        result = replay_skills(
            skills=["skill1"],
            skill_dirs={"skill1": skill_dir},
            project_root=self.tmp_dir,
        )

        assert result.success is True

        # The added file should have the fresh content (not stale)
        assert (self.tmp_dir / "src" / "stale-add.ts").read_text() == "fresh add"
