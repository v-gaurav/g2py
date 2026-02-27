"""Tests for the customize session module."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from skills_engine.constants import CUSTOM_DIR
from skills_engine.customize import (
    abort_customize,
    commit_customize,
    is_customize_active,
    start_customize,
)
from skills_engine.state import compute_file_hash, read_state, record_skill_application

from .conftest import create_minimal_state

if TYPE_CHECKING:
    from pathlib import Path


class TestCustomize:
    @pytest.fixture(autouse=True)
    def _setup(self, g2_dir: Path) -> None:
        self.tmp_dir = g2_dir
        create_minimal_state(g2_dir)
        (g2_dir / CUSTOM_DIR).mkdir(parents=True, exist_ok=True)

    def _setup_tracked_file(self) -> Path:
        """Create a tracked file and register it with a skill application."""
        tracked_file = self.tmp_dir / "src" / "app.ts"
        tracked_file.parent.mkdir(parents=True, exist_ok=True)
        tracked_file.write_text("export const x = 1;")
        record_skill_application(
            "test-skill",
            "1.0.0",
            {"src/app.ts": compute_file_hash(tracked_file)},
        )
        return tracked_file

    def test_start_customize_creates_pending_and_is_active(self) -> None:
        self._setup_tracked_file()

        assert is_customize_active() is False
        start_customize("test customization")
        assert is_customize_active() is True

        pending_path = self.tmp_dir / CUSTOM_DIR / "pending.yaml"
        assert pending_path.exists()

    def test_abort_customize_removes_pending(self) -> None:
        self._setup_tracked_file()

        start_customize("test")
        assert is_customize_active() is True

        abort_customize()
        assert is_customize_active() is False

    def test_commit_customize_with_no_changes_clears_pending(self) -> None:
        self._setup_tracked_file()

        start_customize("no-op")
        commit_customize()

        assert is_customize_active() is False

    def test_commit_customize_with_changes_creates_patch_and_records(self) -> None:
        tracked_file = self._setup_tracked_file()

        # Also create a base file for diff generation
        base_file = self.tmp_dir / ".g2" / "base" / "src" / "app.ts"
        base_file.parent.mkdir(parents=True, exist_ok=True)
        base_file.write_text("export const x = 1;")

        start_customize("add feature")

        # Modify the tracked file
        tracked_file.write_text("export const x = 2;\nexport const y = 3;")

        commit_customize()

        assert is_customize_active() is False
        state = read_state()
        assert state.custom_modifications is not None
        assert len(state.custom_modifications) > 0
        assert state.custom_modifications[0].description == "add feature"

    def test_commit_customize_throws_on_diff_failure(self) -> None:
        tracked_file = self._setup_tracked_file()

        start_customize("diff-error test")

        # Modify the tracked file
        tracked_file.write_text("export const x = 2;")

        # Make the base file a directory to cause diff to exit with code 2
        base_file_path = self.tmp_dir / ".g2" / "base" / "src" / "app.ts"
        base_file_path.mkdir(parents=True, exist_ok=True)

        with pytest.raises(RuntimeError, match="(?i)diff error"):
            commit_customize()

    def test_start_customize_while_active_throws(self) -> None:
        self._setup_tracked_file()

        start_customize("first")
        with pytest.raises(RuntimeError):
            start_customize("second")
