"""Tests for the apply module (applying skill packages)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from skills_engine.apply import apply_skill

from .conftest import (
    create_minimal_state,
    create_skill_package,
    init_git_repo,
)

if TYPE_CHECKING:
    from pathlib import Path


class TestApply:
    @pytest.fixture(autouse=True)
    def _setup(self, g2_dir: Path) -> None:
        self.tmp_dir = g2_dir
        create_minimal_state(g2_dir)
        init_git_repo(g2_dir)

    def test_rejects_when_min_skills_system_version_too_high(self) -> None:
        skill_dir = create_skill_package(
            self.tmp_dir,
            skill="future-skill",
            version="1.0.0",
            core_version="1.0.0",
            adds=[],
            modifies=[],
            min_skills_system_version="99.0.0",
        )

        result = apply_skill(skill_dir)
        assert result.success is False
        assert "99.0.0" in result.error

    def test_executes_post_apply_commands_on_success(self) -> None:
        marker_file = self.tmp_dir / "post-apply-marker.txt"
        skill_dir = create_skill_package(
            self.tmp_dir,
            skill="post-test",
            version="1.0.0",
            core_version="1.0.0",
            adds=["src/newfile.ts"],
            modifies=[],
            add_files={"src/newfile.ts": "export const x = 1;"},
            post_apply=[f'echo "applied" > "{marker_file}"'],
        )

        result = apply_skill(skill_dir)
        assert result.success is True
        assert marker_file.exists()
        assert marker_file.read_text().strip() == "applied"

    def test_rolls_back_on_post_apply_failure(self) -> None:
        (self.tmp_dir / "src").mkdir(parents=True, exist_ok=True)
        existing_file = self.tmp_dir / "src" / "existing.ts"
        existing_file.write_text("original content")

        # Set up base for the modified file
        base_dir = self.tmp_dir / ".g2" / "base" / "src"
        base_dir.mkdir(parents=True, exist_ok=True)
        (base_dir / "existing.ts").write_text("original content")

        skill_dir = create_skill_package(
            self.tmp_dir,
            skill="bad-post",
            version="1.0.0",
            core_version="1.0.0",
            adds=["src/added.ts"],
            modifies=[],
            add_files={"src/added.ts": "new file"},
            post_apply=["false"],  # always fails
        )

        result = apply_skill(skill_dir)
        assert result.success is False
        assert "post_apply" in result.error

        # Added file should be cleaned up
        assert not (self.tmp_dir / "src" / "added.ts").exists()
