"""Tests for the merge module (git merge-file and rerere integration)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from skills_engine.merge import is_git_repo, merge_file, setup_rerere_adapter

from .conftest import init_git_repo


class TestIsGitRepo:
    def test_returns_true_in_git_repo(self, skills_tmp: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        init_git_repo(skills_tmp)
        assert is_git_repo() is True

    def test_returns_false_outside_git_repo(self, skills_tmp: Path) -> None:
        assert is_git_repo() is False


class TestMergeFile:
    @pytest.fixture(autouse=True)
    def _setup_git(self, skills_tmp: Path) -> None:
        self.tmp_dir = skills_tmp
        init_git_repo(skills_tmp)

    def test_clean_merge_with_no_overlapping_changes(self) -> None:
        base = self.tmp_dir / "base.txt"
        current = self.tmp_dir / "current.txt"
        skill = self.tmp_dir / "skill.txt"

        base.write_text("line1\nline2\nline3\n")
        current.write_text("line1-modified\nline2\nline3\n")
        skill.write_text("line1\nline2\nline3-modified\n")

        result = merge_file(current, base, skill)
        assert result.clean is True
        assert result.exit_code == 0

        merged = current.read_text()
        assert "line1-modified" in merged
        assert "line3-modified" in merged

    def test_setup_rerere_adapter_cleans_stale_merge_head(self) -> None:
        git_dir_out = subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            cwd=str(self.tmp_dir),
            capture_output=True,
            text=True,
        ).stdout.strip()
        git_dir = Path(git_dir_out)

        head_hash = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(self.tmp_dir),
            capture_output=True,
            text=True,
        ).stdout.strip()

        # Simulate stale MERGE_HEAD from a previous crash
        (git_dir / "MERGE_HEAD").write_text(head_hash + "\n")
        (git_dir / "MERGE_MSG").write_text("stale merge\n")

        # Write a file for the adapter to work with
        (self.tmp_dir / "test.txt").write_text("conflicted content")

        # setup_rerere_adapter should not throw despite stale MERGE_HEAD
        setup_rerere_adapter("test.txt", "base", "ours", "theirs")

        # MERGE_HEAD should still exist (newly written by setup_rerere_adapter)
        assert (git_dir / "MERGE_HEAD").exists()

    def test_conflict_with_overlapping_changes(self) -> None:
        base = self.tmp_dir / "base.txt"
        current = self.tmp_dir / "current.txt"
        skill = self.tmp_dir / "skill.txt"

        base.write_text("line1\nline2\nline3\n")
        current.write_text("line1-ours\nline2\nline3\n")
        skill.write_text("line1-theirs\nline2\nline3\n")

        result = merge_file(current, base, skill)
        assert result.clean is False
        assert result.exit_code > 0

        merged = current.read_text()
        assert "<<<<<<<" in merged
        assert ">>>>>>>" in merged
