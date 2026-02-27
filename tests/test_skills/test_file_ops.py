"""Tests for the file operations module (rename, delete, move)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from skills_engine.file_ops import execute_file_ops
from skills_engine.types import FileOperation

if TYPE_CHECKING:
    from pathlib import Path


class TestFileOps:
    @pytest.fixture(autouse=True)
    def _setup(self, skills_tmp: Path) -> None:
        self.tmp_dir = skills_tmp

    def test_rename_success(self) -> None:
        (self.tmp_dir / "old.ts").write_text("content")
        result = execute_file_ops(
            [FileOperation(type="rename", from_="old.ts", to="new.ts")],
            self.tmp_dir,
        )
        assert result.success is True
        assert (self.tmp_dir / "new.ts").exists()
        assert not (self.tmp_dir / "old.ts").exists()

    def test_move_success(self) -> None:
        (self.tmp_dir / "file.ts").write_text("content")
        result = execute_file_ops(
            [FileOperation(type="move", from_="file.ts", to="sub/file.ts")],
            self.tmp_dir,
        )
        assert result.success is True
        assert (self.tmp_dir / "sub" / "file.ts").exists()
        assert not (self.tmp_dir / "file.ts").exists()

    def test_delete_success(self) -> None:
        (self.tmp_dir / "remove-me.ts").write_text("content")
        result = execute_file_ops(
            [FileOperation(type="delete", path="remove-me.ts")],
            self.tmp_dir,
        )
        assert result.success is True
        assert not (self.tmp_dir / "remove-me.ts").exists()

    def test_rename_target_exists_produces_error(self) -> None:
        (self.tmp_dir / "a.ts").write_text("a")
        (self.tmp_dir / "b.ts").write_text("b")
        result = execute_file_ops(
            [FileOperation(type="rename", from_="a.ts", to="b.ts")],
            self.tmp_dir,
        )
        assert result.success is False
        assert len(result.errors) > 0

    def test_delete_missing_file_produces_warning_not_error(self) -> None:
        result = execute_file_ops(
            [FileOperation(type="delete", path="nonexistent.ts")],
            self.tmp_dir,
        )
        assert result.success is True
        assert len(result.warnings) > 0

    def test_move_creates_destination_directory(self) -> None:
        (self.tmp_dir / "src.ts").write_text("content")
        result = execute_file_ops(
            [FileOperation(type="move", from_="src.ts", to="deep/nested/dir/src.ts")],
            self.tmp_dir,
        )
        assert result.success is True
        assert (self.tmp_dir / "deep" / "nested" / "dir" / "src.ts").exists()

    def test_path_escape_produces_error(self) -> None:
        (self.tmp_dir / "file.ts").write_text("content")
        result = execute_file_ops(
            [FileOperation(type="rename", from_="file.ts", to="../../escaped.ts")],
            self.tmp_dir,
        )
        assert result.success is False
        assert len(result.errors) > 0

    def test_source_missing_produces_error_for_rename(self) -> None:
        result = execute_file_ops(
            [FileOperation(type="rename", from_="missing.ts", to="new.ts")],
            self.tmp_dir,
        )
        assert result.success is False
        assert len(result.errors) > 0
