"""Tests for the rebase module (patch creation, state update, base flattening)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
import yaml

from skills_engine.rebase import rebase

from .conftest import (
    create_minimal_state,
    init_git_repo,
    write_state,
)

if TYPE_CHECKING:
    from pathlib import Path


class TestRebase:
    @pytest.fixture(autouse=True)
    def _setup(self, g2_dir: Path) -> None:
        self.tmp_dir = g2_dir
        create_minimal_state(g2_dir)

    def test_rebase_with_one_skill_patch_created_state_updated(self) -> None:
        # Set up base file
        base_dir = self.tmp_dir / ".g2" / "base" / "src"
        base_dir.mkdir(parents=True, exist_ok=True)
        (base_dir / "index.ts").write_text("const x = 1;\n")

        # Set up working tree with skill modification
        (self.tmp_dir / "src").mkdir(parents=True, exist_ok=True)
        (self.tmp_dir / "src" / "index.ts").write_text("const x = 1;\nconst y = 2; // added by skill\n")

        # Write state with applied skill
        write_state(
            self.tmp_dir,
            {
                "skills_system_version": "0.1.0",
                "core_version": "1.0.0",
                "applied_skills": [
                    {
                        "name": "test-skill",
                        "version": "1.0.0",
                        "applied_at": datetime.now(UTC).isoformat(),
                        "file_hashes": {
                            "src/index.ts": "abc123",
                        },
                    },
                ],
            },
        )

        init_git_repo(self.tmp_dir)

        result = rebase()

        assert result.success is True
        assert result.files_in_patch > 0
        assert result.rebased_at is not None
        assert result.patch_file is not None

        # Verify patch file exists
        patch_path = self.tmp_dir / ".g2" / "combined.patch"
        assert patch_path.exists()

        patch_content = patch_path.read_text()
        assert "added by skill" in patch_content

        # Verify state was updated
        state_content = (self.tmp_dir / ".g2" / "state.yaml").read_text()
        state = yaml.safe_load(state_content)
        assert state["rebased_at"] is not None
        assert len(state["applied_skills"]) == 1
        assert state["applied_skills"][0]["name"] == "test-skill"

        # File hashes should be updated to actual current values
        current_hash = state["applied_skills"][0]["file_hashes"]["src/index.ts"]
        assert current_hash is not None
        assert current_hash != "abc123"  # Should be recomputed

        # Working tree file should still have the skill's changes
        working_content = (self.tmp_dir / "src" / "index.ts").read_text()
        assert "added by skill" in working_content

    def test_rebase_flattens_base_updated_to_match_working_tree(self) -> None:
        # Set up base file (clean core)
        base_dir = self.tmp_dir / ".g2" / "base" / "src"
        base_dir.mkdir(parents=True, exist_ok=True)
        (base_dir / "index.ts").write_text("const x = 1;\n")

        # Working tree has skill modification
        (self.tmp_dir / "src").mkdir(parents=True, exist_ok=True)
        (self.tmp_dir / "src" / "index.ts").write_text("const x = 1;\nconst y = 2; // skill\n")

        write_state(
            self.tmp_dir,
            {
                "skills_system_version": "0.1.0",
                "core_version": "1.0.0",
                "applied_skills": [
                    {
                        "name": "my-skill",
                        "version": "1.0.0",
                        "applied_at": datetime.now(UTC).isoformat(),
                        "file_hashes": {
                            "src/index.ts": "oldhash",
                        },
                    },
                ],
            },
        )

        init_git_repo(self.tmp_dir)

        result = rebase()
        assert result.success is True

        # Base should now include the skill's changes (flattened)
        base_content = (self.tmp_dir / ".g2" / "base" / "src" / "index.ts").read_text()
        assert "skill" in base_content
        assert base_content == "const x = 1;\nconst y = 2; // skill\n"

    def test_rebase_with_multiple_skills_and_custom_mods(self) -> None:
        # Set up base files
        base_dir = self.tmp_dir / ".g2" / "base"
        (base_dir / "src").mkdir(parents=True, exist_ok=True)
        (base_dir / "src" / "index.ts").write_text("const x = 1;\n")
        (base_dir / "src" / "config.ts").write_text("export const port = 3000;\n")

        # Set up working tree with modifications from multiple skills
        (self.tmp_dir / "src").mkdir(parents=True, exist_ok=True)
        (self.tmp_dir / "src" / "index.ts").write_text("const x = 1;\nconst y = 2; // skill-a\n")
        (self.tmp_dir / "src" / "config.ts").write_text(
            'export const port = 3000;\nexport const host = "0.0.0.0"; // skill-b\n'
        )
        # File added by skill
        (self.tmp_dir / "src" / "plugin.ts").write_text("export const plugin = true;\n")

        write_state(
            self.tmp_dir,
            {
                "skills_system_version": "0.1.0",
                "core_version": "1.0.0",
                "applied_skills": [
                    {
                        "name": "skill-a",
                        "version": "1.0.0",
                        "applied_at": datetime.now(UTC).isoformat(),
                        "file_hashes": {
                            "src/index.ts": "hash-a1",
                        },
                    },
                    {
                        "name": "skill-b",
                        "version": "2.0.0",
                        "applied_at": datetime.now(UTC).isoformat(),
                        "file_hashes": {
                            "src/config.ts": "hash-b1",
                            "src/plugin.ts": "hash-b2",
                        },
                    },
                ],
                "custom_modifications": [
                    {
                        "description": "tweaked config",
                        "applied_at": datetime.now(UTC).isoformat(),
                        "files_modified": ["src/config.ts"],
                        "patch_file": ".g2/custom/001-tweaked-config.patch",
                    },
                ],
            },
        )

        init_git_repo(self.tmp_dir)

        result = rebase()

        assert result.success is True
        assert result.files_in_patch >= 2

        # Verify combined patch includes changes from both skills
        patch_content = (self.tmp_dir / ".g2" / "combined.patch").read_text()
        assert "skill-a" in patch_content
        assert "skill-b" in patch_content

        # Verify state: custom_modifications should be cleared
        state_content = (self.tmp_dir / ".g2" / "state.yaml").read_text()
        state = yaml.safe_load(state_content)
        assert state.get("custom_modifications") is None
        assert state["rebased_at"] is not None

        # applied_skills should still be present (informational)
        assert len(state["applied_skills"]) == 2

        # Base should be flattened -- include all skill changes
        base_index = (self.tmp_dir / ".g2" / "base" / "src" / "index.ts").read_text()
        assert "skill-a" in base_index

        base_config = (self.tmp_dir / ".g2" / "base" / "src" / "config.ts").read_text()
        assert "skill-b" in base_config

    def test_rebase_clears_resolution_cache(self) -> None:
        # Set up base + working tree
        base_dir = self.tmp_dir / ".g2" / "base" / "src"
        base_dir.mkdir(parents=True, exist_ok=True)
        (base_dir / "index.ts").write_text("const x = 1;\n")

        (self.tmp_dir / "src").mkdir(parents=True, exist_ok=True)
        (self.tmp_dir / "src" / "index.ts").write_text("const x = 1;\n// skill\n")

        # Create a fake resolution cache entry
        res_dir = self.tmp_dir / ".g2" / "resolutions" / "skill-a+skill-b"
        res_dir.mkdir(parents=True, exist_ok=True)
        (res_dir / "meta.yaml").write_text("skills: [skill-a, skill-b]\n")

        write_state(
            self.tmp_dir,
            {
                "skills_system_version": "0.1.0",
                "core_version": "1.0.0",
                "applied_skills": [
                    {
                        "name": "my-skill",
                        "version": "1.0.0",
                        "applied_at": datetime.now(UTC).isoformat(),
                        "file_hashes": {"src/index.ts": "hash"},
                    },
                ],
            },
        )

        init_git_repo(self.tmp_dir)

        result = rebase()
        assert result.success is True

        # Resolution cache should be cleared
        resolutions = list((self.tmp_dir / ".g2" / "resolutions").iterdir())
        assert len(resolutions) == 0

    def test_rebase_with_new_base(self) -> None:
        # Set up current base (multi-line so changes don't conflict)
        base_dir = self.tmp_dir / ".g2" / "base"
        (base_dir / "src").mkdir(parents=True, exist_ok=True)
        (base_dir / "src" / "index.ts").write_text("line1\nline2\nline3\nline4\nline5\nline6\nline7\nline8\n")

        # Working tree: skill adds at bottom
        (self.tmp_dir / "src").mkdir(parents=True, exist_ok=True)
        (self.tmp_dir / "src" / "index.ts").write_text(
            "line1\nline2\nline3\nline4\nline5\nline6\nline7\nline8\nskill change\n"
        )

        write_state(
            self.tmp_dir,
            {
                "skills_system_version": "0.1.0",
                "core_version": "1.0.0",
                "applied_skills": [
                    {
                        "name": "my-skill",
                        "version": "1.0.0",
                        "applied_at": datetime.now(UTC).isoformat(),
                        "file_hashes": {
                            "src/index.ts": "oldhash",
                        },
                    },
                ],
            },
        )

        init_git_repo(self.tmp_dir)

        # New base: core update at top
        new_base = self.tmp_dir / "new-core"
        (new_base / "src").mkdir(parents=True, exist_ok=True)
        (new_base / "src" / "index.ts").write_text(
            "core v2 header\nline1\nline2\nline3\nline4\nline5\nline6\nline7\nline8\n"
        )

        result = rebase(new_base)

        assert result.success is True
        assert result.patch_file is not None

        # Verify base was updated to new core
        base_content = (self.tmp_dir / ".g2" / "base" / "src" / "index.ts").read_text()
        assert "core v2 header" in base_content

        # Working tree should have both core v2 and skill changes merged
        working_content = (self.tmp_dir / "src" / "index.ts").read_text()
        assert "core v2 header" in working_content
        assert "skill change" in working_content

        # State should reflect rebase
        state_content = (self.tmp_dir / ".g2" / "state.yaml").read_text()
        state = yaml.safe_load(state_content)
        assert state["rebased_at"] is not None

    def test_rebase_with_new_base_conflict_returns_backup_pending(self) -> None:
        # Set up current base -- short file so changes overlap
        base_dir = self.tmp_dir / ".g2" / "base"
        (base_dir / "src").mkdir(parents=True, exist_ok=True)
        (base_dir / "src" / "index.ts").write_text("const x = 1;\n")

        # Working tree: skill replaces the same line
        (self.tmp_dir / "src").mkdir(parents=True, exist_ok=True)
        (self.tmp_dir / "src" / "index.ts").write_text("const x = 42; // skill override\n")

        write_state(
            self.tmp_dir,
            {
                "skills_system_version": "0.1.0",
                "core_version": "1.0.0",
                "applied_skills": [
                    {
                        "name": "my-skill",
                        "version": "1.0.0",
                        "applied_at": datetime.now(UTC).isoformat(),
                        "file_hashes": {
                            "src/index.ts": "oldhash",
                        },
                    },
                ],
            },
        )

        init_git_repo(self.tmp_dir)

        # New base: also changes the same line -- guaranteed conflict
        new_base = self.tmp_dir / "new-core"
        (new_base / "src").mkdir(parents=True, exist_ok=True)
        (new_base / "src" / "index.ts").write_text("const x = 999; // core v2\n")

        result = rebase(new_base)

        assert result.success is False
        assert "src/index.ts" in result.merge_conflicts
        assert result.backup_pending is True
        assert "Merge conflicts" in result.error

        # combined.patch should still exist
        assert result.patch_file is not None
        patch_path = self.tmp_dir / ".g2" / "combined.patch"
        assert patch_path.exists()

        # Working tree should have conflict markers (not rolled back)
        working_content = (self.tmp_dir / "src" / "index.ts").read_text()
        assert "<<<<<<<" in working_content
        assert ">>>>>>>" in working_content

        # State should NOT be updated yet (conflicts pending)
        state_content = (self.tmp_dir / ".g2" / "state.yaml").read_text()
        state = yaml.safe_load(state_content)
        assert state.get("rebased_at") is None

    def test_error_when_no_skills_applied(self) -> None:
        # State has no applied skills (created by create_minimal_state)
        init_git_repo(self.tmp_dir)

        result = rebase()

        assert result.success is False
        assert "No skills applied" in result.error
        assert result.files_in_patch == 0
