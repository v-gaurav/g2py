"""Tests for the resolution cache module (save, find, load resolutions)."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

import pytest
import yaml

from skills_engine.resolution_cache import (
    find_resolution_dir,
    load_resolutions,
    save_resolution,
)

from .conftest import init_git_repo

if TYPE_CHECKING:
    from pathlib import Path


def _sha256(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()


DUMMY_HASHES = {"base": "aaa", "current": "bbb", "skill": "ccc"}


class TestResolutionCache:
    @pytest.fixture(autouse=True)
    def _setup(self, g2_dir: Path) -> None:
        self.tmp_dir = g2_dir

    def test_find_resolution_dir_returns_none_when_not_found(self) -> None:
        result = find_resolution_dir(["skill-a", "skill-b"], self.tmp_dir)
        assert result is None

    def test_save_resolution_creates_directory_structure(self) -> None:
        save_resolution(
            ["skill-b", "skill-a"],
            [
                {
                    "rel_path": "src/config.ts",
                    "preimage": "conflict content",
                    "resolution": "resolved content",
                    "input_hashes": DUMMY_HASHES,
                },
            ],
            {"core_version": "1.0.0"},
            self.tmp_dir,
        )

        # Skills are sorted, so key is "skill-a+skill-b"
        res_dir = self.tmp_dir / ".g2" / "resolutions" / "skill-a+skill-b"
        assert res_dir.exists()

        # Check preimage and resolution files exist
        assert (res_dir / "src" / "config.ts.preimage").exists()
        assert (res_dir / "src" / "config.ts.resolution").exists()

        # Check meta.yaml exists and has expected fields
        meta_path = res_dir / "meta.yaml"
        assert meta_path.exists()
        meta = yaml.safe_load(meta_path.read_text())
        assert meta["core_version"] == "1.0.0"
        assert meta["skills"] == ["skill-a", "skill-b"]

    def test_save_resolution_writes_file_hashes_to_meta(self) -> None:
        hashes = {
            "base": _sha256("base content"),
            "current": _sha256("current content"),
            "skill": _sha256("skill content"),
        }

        save_resolution(
            ["alpha", "beta"],
            [
                {
                    "rel_path": "src/config.ts",
                    "preimage": "pre",
                    "resolution": "post",
                    "input_hashes": hashes,
                },
            ],
            {},
            self.tmp_dir,
        )

        res_dir = self.tmp_dir / ".g2" / "resolutions" / "alpha+beta"
        meta = yaml.safe_load((res_dir / "meta.yaml").read_text())
        assert meta.get("file_hashes") is not None
        assert meta["file_hashes"]["src/config.ts"] == hashes

    def test_find_resolution_dir_returns_path_after_save(self) -> None:
        save_resolution(
            ["alpha", "beta"],
            [
                {
                    "rel_path": "file.ts",
                    "preimage": "pre",
                    "resolution": "post",
                    "input_hashes": DUMMY_HASHES,
                },
            ],
            {},
            self.tmp_dir,
        )

        result = find_resolution_dir(["alpha", "beta"], self.tmp_dir)
        assert result is not None
        assert "alpha+beta" in str(result)

    def test_find_resolution_dir_finds_shipped_resolutions(self) -> None:
        shipped_dir = self.tmp_dir / ".claude" / "resolutions" / "alpha+beta"
        shipped_dir.mkdir(parents=True, exist_ok=True)
        (shipped_dir / "meta.yaml").write_text("skills: [alpha, beta]\n")

        result = find_resolution_dir(["alpha", "beta"], self.tmp_dir)
        assert result is not None
        assert ".claude/resolutions/alpha+beta" in str(result)

    def test_find_resolution_dir_prefers_shipped_over_project_level(self) -> None:
        # Create both shipped and project-level
        shipped_dir = self.tmp_dir / ".claude" / "resolutions" / "a+b"
        shipped_dir.mkdir(parents=True, exist_ok=True)
        (shipped_dir / "meta.yaml").write_text("skills: [a, b]\n")

        save_resolution(
            ["a", "b"],
            [
                {
                    "rel_path": "f.ts",
                    "preimage": "x",
                    "resolution": "project",
                    "input_hashes": DUMMY_HASHES,
                },
            ],
            {},
            self.tmp_dir,
        )

        result = find_resolution_dir(["a", "b"], self.tmp_dir)
        assert ".claude/resolutions/a+b" in str(result)

    def test_skills_are_sorted_so_order_does_not_matter(self) -> None:
        save_resolution(
            ["zeta", "alpha"],
            [
                {
                    "rel_path": "f.ts",
                    "preimage": "a",
                    "resolution": "b",
                    "input_hashes": DUMMY_HASHES,
                },
            ],
            {},
            self.tmp_dir,
        )

        # Find with reversed order should still work
        result = find_resolution_dir(["alpha", "zeta"], self.tmp_dir)
        assert result is not None

        # Also works with original order
        result2 = find_resolution_dir(["zeta", "alpha"], self.tmp_dir)
        assert result2 is not None
        assert result == result2


class TestLoadResolutionsHashVerification:
    BASE_CONTENT = "base file content"
    CURRENT_CONTENT = "current file content"
    SKILL_CONTENT = "skill file content"
    PREIMAGE_CONTENT = "preimage with conflict markers"
    RESOLUTION_CONTENT = "resolved content"
    RERERE_HASH = "abc123def456"

    @pytest.fixture(autouse=True)
    def _setup(self, g2_dir: Path) -> None:
        self.tmp_dir = g2_dir
        init_git_repo(g2_dir)

    def _setup_resolution_dir(self, file_hashes: dict[str, dict[str, str]]) -> Path:
        res_dir = self.tmp_dir / ".claude" / "resolutions" / "alpha+beta"
        (res_dir / "src").mkdir(parents=True, exist_ok=True)

        (res_dir / "src" / "config.ts.preimage").write_text(self.PREIMAGE_CONTENT)
        (res_dir / "src" / "config.ts.resolution").write_text(self.RESOLUTION_CONTENT)
        (res_dir / "src" / "config.ts.preimage.hash").write_text(self.RERERE_HASH)

        meta = {
            "skills": ["alpha", "beta"],
            "apply_order": ["alpha", "beta"],
            "core_version": "1.0.0",
            "resolved_at": "2024-01-01T00:00:00Z",
            "tested": True,
            "test_passed": True,
            "resolution_source": "maintainer",
            "input_hashes": {},
            "output_hash": "",
            "file_hashes": file_hashes,
        }
        (res_dir / "meta.yaml").write_text(yaml.safe_dump(meta))

        return res_dir

    def _setup_input_files(self) -> None:
        (self.tmp_dir / ".g2" / "base" / "src").mkdir(parents=True, exist_ok=True)
        (self.tmp_dir / ".g2" / "base" / "src" / "config.ts").write_text(self.BASE_CONTENT)
        (self.tmp_dir / "src").mkdir(parents=True, exist_ok=True)
        (self.tmp_dir / "src" / "config.ts").write_text(self.CURRENT_CONTENT)

    def _create_skill_dir(self) -> Path:
        skill_dir = self.tmp_dir / "skill-pkg"
        (skill_dir / "modify" / "src").mkdir(parents=True, exist_ok=True)
        (skill_dir / "modify" / "src" / "config.ts").write_text(self.SKILL_CONTENT)
        return skill_dir

    def test_loads_with_matching_file_hashes(self) -> None:
        self._setup_input_files()
        skill_dir = self._create_skill_dir()

        self._setup_resolution_dir(
            {
                "src/config.ts": {
                    "base": _sha256(self.BASE_CONTENT),
                    "current": _sha256(self.CURRENT_CONTENT),
                    "skill": _sha256(self.SKILL_CONTENT),
                },
            }
        )

        result = load_resolutions(["alpha", "beta"], self.tmp_dir, skill_dir)
        assert result is True

        # Verify rr-cache entry was created
        git_dir = self.tmp_dir / ".git"
        cache_entry = git_dir / "rr-cache" / self.RERERE_HASH
        assert (cache_entry / "preimage").exists()
        assert (cache_entry / "postimage").exists()

    def test_skips_pair_with_mismatched_base_hash(self) -> None:
        self._setup_input_files()
        skill_dir = self._create_skill_dir()

        self._setup_resolution_dir(
            {
                "src/config.ts": {
                    "base": "wrong_hash",
                    "current": _sha256(self.CURRENT_CONTENT),
                    "skill": _sha256(self.SKILL_CONTENT),
                },
            }
        )

        result = load_resolutions(["alpha", "beta"], self.tmp_dir, skill_dir)
        assert result is False

        # rr-cache entry should NOT be created
        git_dir = self.tmp_dir / ".git"
        assert not (git_dir / "rr-cache" / self.RERERE_HASH).exists()

    def test_skips_pair_with_mismatched_current_hash(self) -> None:
        self._setup_input_files()
        skill_dir = self._create_skill_dir()

        self._setup_resolution_dir(
            {
                "src/config.ts": {
                    "base": _sha256(self.BASE_CONTENT),
                    "current": "wrong_hash",
                    "skill": _sha256(self.SKILL_CONTENT),
                },
            }
        )

        result = load_resolutions(["alpha", "beta"], self.tmp_dir, skill_dir)
        assert result is False

    def test_skips_pair_with_mismatched_skill_hash(self) -> None:
        self._setup_input_files()
        skill_dir = self._create_skill_dir()

        self._setup_resolution_dir(
            {
                "src/config.ts": {
                    "base": _sha256(self.BASE_CONTENT),
                    "current": _sha256(self.CURRENT_CONTENT),
                    "skill": "wrong_hash",
                },
            }
        )

        result = load_resolutions(["alpha", "beta"], self.tmp_dir, skill_dir)
        assert result is False

    def test_skips_pair_with_no_file_hashes_entry(self) -> None:
        self._setup_input_files()
        skill_dir = self._create_skill_dir()

        # file_hashes exists but doesn't include src/config.ts
        self._setup_resolution_dir({})

        result = load_resolutions(["alpha", "beta"], self.tmp_dir, skill_dir)
        assert result is False
