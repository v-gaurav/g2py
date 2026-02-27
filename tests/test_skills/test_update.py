"""Tests for the update module (preview and apply core updates)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import pytest

from skills_engine.update import apply_update, preview_update

from .conftest import init_git_repo, write_state

if TYPE_CHECKING:
    from pathlib import Path


class TestUpdate:
    @pytest.fixture(autouse=True)
    def _setup(self, g2_dir: Path) -> None:
        self.tmp_dir = g2_dir
        init_git_repo(g2_dir)

    def _write_state(self, state: dict[str, Any]) -> None:
        write_state(self.tmp_dir, state)

    def _create_new_core_dir(self, files: dict[str, str]) -> Path:
        new_core_dir = self.tmp_dir / "new-core"
        new_core_dir.mkdir(parents=True, exist_ok=True)

        for rel_path, content in files.items():
            full_path = new_core_dir / rel_path
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(content)

        return new_core_dir


class TestPreviewUpdate(TestUpdate):
    def test_detects_new_files_in_update(self) -> None:
        self._write_state(
            {
                "skills_system_version": "0.1.0",
                "core_version": "1.0.0",
                "applied_skills": [],
            }
        )

        new_core_dir = self._create_new_core_dir(
            {
                "src/new-file.ts": "export const x = 1;",
            }
        )

        preview = preview_update(new_core_dir)

        assert "src/new-file.ts" in preview.files_changed
        assert preview.current_version == "1.0.0"

    def test_detects_changed_files_vs_base(self) -> None:
        base_dir = self.tmp_dir / ".g2" / "base"
        (base_dir / "src").mkdir(parents=True, exist_ok=True)
        (base_dir / "src" / "index.ts").write_text("original")

        self._write_state(
            {
                "skills_system_version": "0.1.0",
                "core_version": "1.0.0",
                "applied_skills": [],
            }
        )

        new_core_dir = self._create_new_core_dir(
            {
                "src/index.ts": "modified",
            }
        )

        preview = preview_update(new_core_dir)
        assert "src/index.ts" in preview.files_changed

    def test_does_not_list_unchanged_files(self) -> None:
        base_dir = self.tmp_dir / ".g2" / "base"
        (base_dir / "src").mkdir(parents=True, exist_ok=True)
        (base_dir / "src" / "index.ts").write_text("same content")

        self._write_state(
            {
                "skills_system_version": "0.1.0",
                "core_version": "1.0.0",
                "applied_skills": [],
            }
        )

        new_core_dir = self._create_new_core_dir(
            {
                "src/index.ts": "same content",
            }
        )

        preview = preview_update(new_core_dir)
        assert "src/index.ts" not in preview.files_changed

    def test_identifies_conflict_risk_with_applied_skills(self) -> None:
        base_dir = self.tmp_dir / ".g2" / "base"
        (base_dir / "src").mkdir(parents=True, exist_ok=True)
        (base_dir / "src" / "index.ts").write_text("original")

        self._write_state(
            {
                "skills_system_version": "0.1.0",
                "core_version": "1.0.0",
                "applied_skills": [
                    {
                        "name": "telegram",
                        "version": "1.0.0",
                        "applied_at": datetime.now(UTC).isoformat(),
                        "file_hashes": {"src/index.ts": "abc123"},
                    },
                ],
            }
        )

        new_core_dir = self._create_new_core_dir(
            {
                "src/index.ts": "updated core",
            }
        )

        preview = preview_update(new_core_dir)
        assert "src/index.ts" in preview.conflict_risk

    def test_identifies_custom_patches_at_risk(self) -> None:
        base_dir = self.tmp_dir / ".g2" / "base"
        (base_dir / "src").mkdir(parents=True, exist_ok=True)
        (base_dir / "src" / "config.ts").write_text("original")

        self._write_state(
            {
                "skills_system_version": "0.1.0",
                "core_version": "1.0.0",
                "applied_skills": [],
                "custom_modifications": [
                    {
                        "description": "custom tweak",
                        "applied_at": datetime.now(UTC).isoformat(),
                        "files_modified": ["src/config.ts"],
                        "patch_file": ".g2/custom/001-tweak.patch",
                    },
                ],
            }
        )

        new_core_dir = self._create_new_core_dir(
            {
                "src/config.ts": "updated core config",
            }
        )

        preview = preview_update(new_core_dir)
        assert "src/config.ts" in preview.custom_patches_at_risk

    def test_reads_version_from_package_json_in_new_core(self) -> None:
        self._write_state(
            {
                "skills_system_version": "0.1.0",
                "core_version": "1.0.0",
                "applied_skills": [],
            }
        )

        new_core_dir = self._create_new_core_dir(
            {
                "package.json": json.dumps({"version": "2.0.0"}),
            }
        )

        preview = preview_update(new_core_dir)
        assert preview.new_version == "2.0.0"

    def test_detects_files_deleted_in_new_core(self) -> None:
        base_dir = self.tmp_dir / ".g2" / "base"
        (base_dir / "src").mkdir(parents=True, exist_ok=True)
        (base_dir / "src" / "index.ts").write_text("keep this")
        (base_dir / "src" / "removed.ts").write_text("delete this")

        self._write_state(
            {
                "skills_system_version": "0.1.0",
                "core_version": "1.0.0",
                "applied_skills": [],
            }
        )

        # New core only has index.ts -- removed.ts is gone
        new_core_dir = self._create_new_core_dir(
            {
                "src/index.ts": "keep this",
            }
        )

        preview = preview_update(new_core_dir)
        assert "src/removed.ts" in preview.files_deleted
        assert "src/removed.ts" not in preview.files_changed


class TestApplyUpdate(TestUpdate):
    def test_rejects_when_customize_session_is_active(self) -> None:
        self._write_state(
            {
                "skills_system_version": "0.1.0",
                "core_version": "1.0.0",
                "applied_skills": [],
            }
        )

        # Create the pending.yaml that indicates active customize
        custom_dir = self.tmp_dir / ".g2" / "custom"
        custom_dir.mkdir(parents=True, exist_ok=True)
        (custom_dir / "pending.yaml").write_text("active: true")

        new_core_dir = self._create_new_core_dir(
            {
                "src/index.ts": "new content",
            }
        )

        result = apply_update(new_core_dir)
        assert result.success is False
        assert "customize session" in result.error

    def test_copies_new_files_that_do_not_exist(self) -> None:
        self._write_state(
            {
                "skills_system_version": "0.1.0",
                "core_version": "1.0.0",
                "applied_skills": [],
            }
        )

        new_core_dir = self._create_new_core_dir(
            {
                "src/brand-new.ts": "export const fresh = true;",
            }
        )

        result = apply_update(new_core_dir)
        assert result.error is None
        assert result.success is True
        assert (self.tmp_dir / "src" / "brand-new.ts").read_text() == "export const fresh = true;"

    def test_performs_clean_three_way_merge(self) -> None:
        # Set up base
        base_dir = self.tmp_dir / ".g2" / "base"
        (base_dir / "src").mkdir(parents=True, exist_ok=True)
        (base_dir / "src" / "index.ts").write_text("line 1\nline 2\nline 3\n")

        # Current has user changes at the bottom
        (self.tmp_dir / "src").mkdir(parents=True, exist_ok=True)
        (self.tmp_dir / "src" / "index.ts").write_text("line 1\nline 2\nline 3\nuser addition\n")

        self._write_state(
            {
                "skills_system_version": "0.1.0",
                "core_version": "1.0.0",
                "applied_skills": [],
            }
        )

        # New core changes at the top
        new_core_dir = self._create_new_core_dir(
            {
                "src/index.ts": "core update\nline 1\nline 2\nline 3\n",
                "package.json": json.dumps({"version": "2.0.0"}),
            }
        )

        result = apply_update(new_core_dir)
        assert result.success is True
        assert result.new_version == "2.0.0"

        merged = (self.tmp_dir / "src" / "index.ts").read_text()
        assert "core update" in merged
        assert "user addition" in merged

    def test_updates_base_directory_after_successful_merge(self) -> None:
        base_dir = self.tmp_dir / ".g2" / "base"
        (base_dir / "src").mkdir(parents=True, exist_ok=True)
        (base_dir / "src" / "index.ts").write_text("old base")

        (self.tmp_dir / "src").mkdir(parents=True, exist_ok=True)
        (self.tmp_dir / "src" / "index.ts").write_text("old base")

        self._write_state(
            {
                "skills_system_version": "0.1.0",
                "core_version": "1.0.0",
                "applied_skills": [],
            }
        )

        new_core_dir = self._create_new_core_dir(
            {
                "src/index.ts": "new base content",
            }
        )

        apply_update(new_core_dir)

        new_base = (self.tmp_dir / ".g2" / "base" / "src" / "index.ts").read_text()
        assert new_base == "new base content"

    def test_updates_core_version_in_state_after_success(self) -> None:
        self._write_state(
            {
                "skills_system_version": "0.1.0",
                "core_version": "1.0.0",
                "applied_skills": [],
            }
        )

        new_core_dir = self._create_new_core_dir(
            {
                "package.json": json.dumps({"version": "2.0.0"}),
            }
        )

        result = apply_update(new_core_dir)

        assert result.success is True
        assert result.previous_version == "1.0.0"
        assert result.new_version == "2.0.0"

        # Verify state file was updated
        from skills_engine.state import read_state

        state = read_state()
        assert state.core_version == "2.0.0"

    def test_restores_backup_on_merge_conflict(self) -> None:
        base_dir = self.tmp_dir / ".g2" / "base"
        (base_dir / "src").mkdir(parents=True, exist_ok=True)
        (base_dir / "src" / "index.ts").write_text("line 1\nline 2\nline 3\n")

        # Current has conflicting change on same line
        (self.tmp_dir / "src").mkdir(parents=True, exist_ok=True)
        (self.tmp_dir / "src" / "index.ts").write_text("line 1\nuser changed line 2\nline 3\n")

        self._write_state(
            {
                "skills_system_version": "0.1.0",
                "core_version": "1.0.0",
                "applied_skills": [],
            }
        )

        # New core also changes line 2 -- guaranteed conflict
        new_core_dir = self._create_new_core_dir(
            {
                "src/index.ts": "line 1\ncore changed line 2\nline 3\n",
            }
        )

        result = apply_update(new_core_dir)

        assert result.success is False
        assert "src/index.ts" in result.merge_conflicts
        assert result.backup_pending is True

        # File should have conflict markers
        content = (self.tmp_dir / "src" / "index.ts").read_text()
        assert "<<<<<<<" in content
        assert ">>>>>>>" in content

    def test_removes_files_deleted_in_new_core(self) -> None:
        base_dir = self.tmp_dir / ".g2" / "base"
        (base_dir / "src").mkdir(parents=True, exist_ok=True)
        (base_dir / "src" / "index.ts").write_text("keep")
        (base_dir / "src" / "removed.ts").write_text("old content")

        # Working tree has both files
        (self.tmp_dir / "src").mkdir(parents=True, exist_ok=True)
        (self.tmp_dir / "src" / "index.ts").write_text("keep")
        (self.tmp_dir / "src" / "removed.ts").write_text("old content")

        self._write_state(
            {
                "skills_system_version": "0.1.0",
                "core_version": "1.0.0",
                "applied_skills": [],
            }
        )

        # New core only has index.ts
        new_core_dir = self._create_new_core_dir(
            {
                "src/index.ts": "keep",
            }
        )

        result = apply_update(new_core_dir)
        assert result.success is True
        assert (self.tmp_dir / "src" / "index.ts").exists()
        assert not (self.tmp_dir / "src" / "removed.ts").exists()
