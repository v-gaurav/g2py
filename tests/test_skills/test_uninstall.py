"""Tests for the uninstall module (removing applied skills)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
import yaml

from skills_engine.uninstall import uninstall_skill

from .conftest import init_git_repo, write_state

if TYPE_CHECKING:
    from pathlib import Path


class TestUninstall:
    @pytest.fixture(autouse=True)
    def _setup(self, g2_dir: Path) -> None:
        self.tmp_dir = g2_dir
        init_git_repo(g2_dir)

    def _setup_skill_package(
        self,
        name: str,
        *,
        adds: dict[str, str] | None = None,
        modifies: dict[str, str] | None = None,
    ) -> None:
        skill_dir = self.tmp_dir / ".claude" / "skills" / name
        skill_dir.mkdir(parents=True, exist_ok=True)

        adds_list = list((adds or {}).keys())
        modifies_list = list((modifies or {}).keys())

        (skill_dir / "manifest.yaml").write_text(
            yaml.safe_dump(
                {
                    "skill": name,
                    "version": "1.0.0",
                    "core_version": "1.0.0",
                    "adds": adds_list,
                    "modifies": modifies_list,
                }
            )
        )

        if adds:
            add_dir = skill_dir / "add"
            for rel_path, content in adds.items():
                full_path = add_dir / rel_path
                full_path.parent.mkdir(parents=True, exist_ok=True)
                full_path.write_text(content)

        if modifies:
            mod_dir = skill_dir / "modify"
            for rel_path, content in modifies.items():
                full_path = mod_dir / rel_path
                full_path.parent.mkdir(parents=True, exist_ok=True)
                full_path.write_text(content)

    def test_returns_error_for_non_applied_skill(self) -> None:
        write_state(
            self.tmp_dir,
            {
                "skills_system_version": "0.1.0",
                "core_version": "1.0.0",
                "applied_skills": [],
            },
        )

        result = uninstall_skill("nonexistent")
        assert result.success is False
        assert "not applied" in result.error

    def test_blocks_uninstall_after_rebase(self) -> None:
        write_state(
            self.tmp_dir,
            {
                "skills_system_version": "0.1.0",
                "core_version": "1.0.0",
                "rebased_at": datetime.now(UTC).isoformat(),
                "applied_skills": [
                    {
                        "name": "telegram",
                        "version": "1.0.0",
                        "applied_at": datetime.now(UTC).isoformat(),
                        "file_hashes": {"src/config.ts": "abc"},
                    },
                ],
            },
        )

        result = uninstall_skill("telegram")
        assert result.success is False
        assert "Cannot uninstall" in result.error
        assert "after rebase" in result.error

    def test_returns_custom_patch_warning(self) -> None:
        write_state(
            self.tmp_dir,
            {
                "skills_system_version": "0.1.0",
                "core_version": "1.0.0",
                "applied_skills": [
                    {
                        "name": "telegram",
                        "version": "1.0.0",
                        "applied_at": datetime.now(UTC).isoformat(),
                        "file_hashes": {},
                        "custom_patch": ".g2/custom/001.patch",
                        "custom_patch_description": "My tweak",
                    },
                ],
            },
        )

        result = uninstall_skill("telegram")
        assert result.success is False
        assert "custom patch" in result.custom_patch_warning
        assert "My tweak" in result.custom_patch_warning

    def test_uninstalls_only_skill_files_reset_to_base(self) -> None:
        # Set up base
        base_dir = self.tmp_dir / ".g2" / "base" / "src"
        base_dir.mkdir(parents=True, exist_ok=True)
        (base_dir / "config.ts").write_text("base config\n")

        # Set up current files (as if skill was applied)
        (self.tmp_dir / "src").mkdir(parents=True, exist_ok=True)
        (self.tmp_dir / "src" / "config.ts").write_text("base config\ntelegram config\n")
        (self.tmp_dir / "src" / "telegram.ts").write_text("telegram code\n")

        # Set up skill package in .claude/skills/
        self._setup_skill_package(
            "telegram",
            adds={"src/telegram.ts": "telegram code\n"},
            modifies={"src/config.ts": "base config\ntelegram config\n"},
        )

        write_state(
            self.tmp_dir,
            {
                "skills_system_version": "0.1.0",
                "core_version": "1.0.0",
                "applied_skills": [
                    {
                        "name": "telegram",
                        "version": "1.0.0",
                        "applied_at": datetime.now(UTC).isoformat(),
                        "file_hashes": {
                            "src/config.ts": "abc",
                            "src/telegram.ts": "def",
                        },
                    },
                ],
            },
        )

        result = uninstall_skill("telegram")
        assert result.success is True
        assert result.skill == "telegram"

        # config.ts should be reset to base
        assert (self.tmp_dir / "src" / "config.ts").read_text() == "base config\n"

        # telegram.ts (add-only) should be removed
        assert not (self.tmp_dir / "src" / "telegram.ts").exists()

    def test_uninstalls_one_of_two_other_preserved(self) -> None:
        # Set up base
        base_dir = self.tmp_dir / ".g2" / "base" / "src"
        base_dir.mkdir(parents=True, exist_ok=True)
        (base_dir / "config.ts").write_text("line1\nline2\nline3\nline4\nline5\n")

        # Current has both skills applied
        (self.tmp_dir / "src").mkdir(parents=True, exist_ok=True)
        (self.tmp_dir / "src" / "config.ts").write_text(
            "telegram import\nline1\nline2\nline3\nline4\nline5\ndiscord import\n"
        )
        (self.tmp_dir / "src" / "telegram.ts").write_text("tg code\n")
        (self.tmp_dir / "src" / "discord.ts").write_text("dc code\n")

        # Set up both skill packages
        self._setup_skill_package(
            "telegram",
            adds={"src/telegram.ts": "tg code\n"},
            modifies={
                "src/config.ts": "telegram import\nline1\nline2\nline3\nline4\nline5\n",
            },
        )

        self._setup_skill_package(
            "discord",
            adds={"src/discord.ts": "dc code\n"},
            modifies={
                "src/config.ts": "line1\nline2\nline3\nline4\nline5\ndiscord import\n",
            },
        )

        write_state(
            self.tmp_dir,
            {
                "skills_system_version": "0.1.0",
                "core_version": "1.0.0",
                "applied_skills": [
                    {
                        "name": "telegram",
                        "version": "1.0.0",
                        "applied_at": datetime.now(UTC).isoformat(),
                        "file_hashes": {
                            "src/config.ts": "abc",
                            "src/telegram.ts": "def",
                        },
                    },
                    {
                        "name": "discord",
                        "version": "1.0.0",
                        "applied_at": datetime.now(UTC).isoformat(),
                        "file_hashes": {
                            "src/config.ts": "ghi",
                            "src/discord.ts": "jkl",
                        },
                    },
                ],
            },
        )

        result = uninstall_skill("telegram")
        assert result.success is True

        # discord.ts should still exist
        assert (self.tmp_dir / "src" / "discord.ts").exists()

        # telegram.ts should be gone
        assert not (self.tmp_dir / "src" / "telegram.ts").exists()

        # config should have discord import but not telegram
        config = (self.tmp_dir / "src" / "config.ts").read_text()
        assert "discord import" in config
        assert "telegram import" not in config
