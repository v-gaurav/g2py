"""Tests for the backup module (create, restore, clear)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from skills_engine.backup import clear_backup, create_backup, restore_backup

if TYPE_CHECKING:
    from pathlib import Path


class TestBackup:
    @pytest.fixture(autouse=True)
    def _setup(self, g2_dir: Path) -> None:
        self.tmp_dir = g2_dir

    def test_create_and_restore_backup(self) -> None:
        src_dir = self.tmp_dir / "src"
        src_dir.mkdir(parents=True, exist_ok=True)
        (src_dir / "app.ts").write_text("original content")

        create_backup(["src/app.ts"])

        (src_dir / "app.ts").write_text("modified content")
        assert (src_dir / "app.ts").read_text() == "modified content"

        restore_backup()
        assert (src_dir / "app.ts").read_text() == "original content"

    def test_create_backup_skips_missing_files(self) -> None:
        create_backup(["does-not-exist.ts"])

    def test_clear_backup_removes_directory(self) -> None:
        src_dir = self.tmp_dir / "src"
        src_dir.mkdir(parents=True, exist_ok=True)
        (src_dir / "app.ts").write_text("content")
        create_backup(["src/app.ts"])

        backup_dir = self.tmp_dir / ".g2" / "backup"
        assert backup_dir.exists()

        clear_backup()
        assert not backup_dir.exists()

    def test_create_backup_writes_tombstone_for_nonexistent_files(self) -> None:
        create_backup(["src/newfile.ts"])

        tombstone = self.tmp_dir / ".g2" / "backup" / "src" / "newfile.ts.tombstone"
        assert tombstone.exists()

    def test_restore_backup_deletes_files_with_tombstone_markers(self) -> None:
        # Create backup first -- file doesn't exist yet, so tombstone is written
        create_backup(["src/added.ts"])

        # Now the file gets created (simulating skill apply)
        file_path = self.tmp_dir / "src" / "added.ts"
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text("new content")
        assert file_path.exists()

        # Restore should delete the file (tombstone means it didn't exist before)
        restore_backup()
        assert not file_path.exists()

    def test_restore_backup_is_noop_when_empty_or_missing(self) -> None:
        clear_backup()
        restore_backup()  # should not raise
