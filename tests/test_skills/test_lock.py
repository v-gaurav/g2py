"""Tests for the file-based locking module."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from skills_engine.constants import LOCK_FILE
from skills_engine.lock import acquire_lock, is_locked, release_lock

if TYPE_CHECKING:
    from pathlib import Path


class TestLock:
    @pytest.fixture(autouse=True)
    def _setup(self, skills_tmp: Path) -> None:
        self.tmp_dir = skills_tmp
        (skills_tmp / ".g2").mkdir(parents=True, exist_ok=True)

    def test_acquire_lock_returns_release_function(self) -> None:
        release = acquire_lock()
        assert callable(release)
        assert (self.tmp_dir / LOCK_FILE).exists()
        release()

    def test_release_lock_removes_lock_file(self) -> None:
        acquire_lock()
        assert (self.tmp_dir / LOCK_FILE).exists()
        release_lock()
        assert not (self.tmp_dir / LOCK_FILE).exists()

    def test_acquire_after_release_succeeds(self) -> None:
        release1 = acquire_lock()
        release1()
        release2 = acquire_lock()
        assert callable(release2)
        release2()

    def test_is_locked_returns_true_when_locked(self) -> None:
        release = acquire_lock()
        assert is_locked() is True
        release()

    def test_is_locked_returns_false_when_released(self) -> None:
        release = acquire_lock()
        release()
        assert is_locked() is False

    def test_is_locked_returns_false_when_no_lock_exists(self) -> None:
        assert is_locked() is False
