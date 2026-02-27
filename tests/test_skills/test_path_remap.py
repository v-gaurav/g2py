"""Tests for the path remap module."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from skills_engine.path_remap import load_path_remap, record_path_remap, resolve_path_remap

from .conftest import create_minimal_state

if TYPE_CHECKING:
    from pathlib import Path


class TestResolvePathRemap:
    def test_returns_remapped_path_when_entry_exists(self) -> None:
        remap = {"src/old.ts": "src/new.ts"}
        assert resolve_path_remap("src/old.ts", remap) == "src/new.ts"

    def test_returns_original_path_when_no_remap_entry(self) -> None:
        remap = {"src/old.ts": "src/new.ts"}
        assert resolve_path_remap("src/other.ts", remap) == "src/other.ts"

    def test_returns_original_path_when_remap_is_empty(self) -> None:
        assert resolve_path_remap("src/file.ts", {}) == "src/file.ts"


class TestLoadPathRemap:
    @pytest.fixture(autouse=True)
    def _setup(self, g2_dir: Path) -> None:
        self.tmp_dir = g2_dir
        create_minimal_state(g2_dir)

    def test_returns_empty_dict_when_no_remap_in_state(self) -> None:
        remap = load_path_remap()
        assert remap == {}

    def test_returns_remap_from_state(self) -> None:
        record_path_remap({"src/a.ts": "src/b.ts"})
        remap = load_path_remap()
        assert remap == {"src/a.ts": "src/b.ts"}


class TestRecordPathRemap:
    @pytest.fixture(autouse=True)
    def _setup(self, g2_dir: Path) -> None:
        self.tmp_dir = g2_dir
        create_minimal_state(g2_dir)

    def test_records_new_remap_entries(self) -> None:
        record_path_remap({"src/old.ts": "src/new.ts"})
        assert load_path_remap() == {"src/old.ts": "src/new.ts"}

    def test_merges_with_existing_remap(self) -> None:
        record_path_remap({"src/a.ts": "src/b.ts"})
        record_path_remap({"src/c.ts": "src/d.ts"})
        assert load_path_remap() == {
            "src/a.ts": "src/b.ts",
            "src/c.ts": "src/d.ts",
        }

    def test_overwrites_existing_key_on_conflict(self) -> None:
        record_path_remap({"src/a.ts": "src/b.ts"})
        record_path_remap({"src/a.ts": "src/c.ts"})
        assert load_path_remap() == {"src/a.ts": "src/c.ts"}
