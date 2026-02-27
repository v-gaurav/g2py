"""Shared fixtures for skills engine tests."""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING, Any

import pytest
import yaml

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture()
def skills_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create a temp directory and chdir into it.

    Equivalent of createTempDir + process.chdir in the TS helpers.
    """
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture()
def g2_dir(skills_tmp: Path) -> Path:
    """Set up .g2/base/src and .g2/backup directories.

    Equivalent of setupG2Dir in the TS helpers.
    """
    (skills_tmp / ".g2" / "base" / "src").mkdir(parents=True, exist_ok=True)
    (skills_tmp / ".g2" / "backup").mkdir(parents=True, exist_ok=True)
    return skills_tmp


def write_state(tmp_dir: Path, state: dict[str, Any]) -> None:
    """Write a YAML state file to .g2/state.yaml."""
    state_path = tmp_dir / ".g2" / "state.yaml"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(yaml.safe_dump(state), encoding="utf-8")


def create_minimal_state(tmp_dir: Path) -> None:
    """Write a minimal skills state file."""
    write_state(
        tmp_dir,
        {
            "skills_system_version": "0.1.0",
            "core_version": "1.0.0",
            "applied_skills": [],
        },
    )


def create_skill_package(
    tmp_dir: Path,
    *,
    skill: str = "test-skill",
    version: str = "1.0.0",
    core_version: str = "1.0.0",
    adds: list[str] | None = None,
    modifies: list[str] | None = None,
    add_files: dict[str, str] | None = None,
    modify_files: dict[str, str] | None = None,
    conflicts: list[str] | None = None,
    depends: list[str] | None = None,
    test: str | None = None,
    structured: dict[str, Any] | None = None,
    file_ops: list[dict[str, Any]] | None = None,
    post_apply: list[str] | None = None,
    min_skills_system_version: str | None = None,
    dir_name: str = "skill-pkg",
) -> Path:
    """Create a skill package directory with manifest and optional files.

    Equivalent of createSkillPackage in the TS helpers.
    """
    skill_dir = tmp_dir / dir_name
    skill_dir.mkdir(parents=True, exist_ok=True)

    manifest: dict[str, Any] = {
        "skill": skill,
        "version": version,
        "description": "Test skill",
        "core_version": core_version,
        "adds": adds or [],
        "modifies": modifies or [],
        "conflicts": conflicts or [],
        "depends": depends or [],
    }
    if test is not None:
        manifest["test"] = test
    if structured is not None:
        manifest["structured"] = structured
    if file_ops is not None:
        manifest["file_ops"] = file_ops
    if post_apply is not None:
        manifest["post_apply"] = post_apply
    if min_skills_system_version is not None:
        manifest["min_skills_system_version"] = min_skills_system_version

    (skill_dir / "manifest.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")

    if add_files:
        add_dir = skill_dir / "add"
        for rel_path, content in add_files.items():
            full_path = add_dir / rel_path
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(content, encoding="utf-8")

    if modify_files:
        mod_dir = skill_dir / "modify"
        for rel_path, content in modify_files.items():
            full_path = mod_dir / rel_path
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(content, encoding="utf-8")

    return skill_dir


def init_git_repo(directory: Path) -> None:
    """Initialize a git repo with an initial commit.

    Equivalent of initGitRepo in the TS helpers.
    """
    run_opts = {"cwd": str(directory), "capture_output": True, "text": True}
    subprocess.run(["git", "init"], **run_opts, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], **run_opts, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], **run_opts, check=True)
    subprocess.run(["git", "config", "rerere.enabled", "true"], **run_opts, check=True)
    (directory / ".gitignore").write_text("__pycache__\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], **run_opts, check=True)
    subprocess.run(["git", "commit", "-m", "init"], **run_opts, check=True)
