"""Tests for the structured merge module (npm deps, env additions, docker compose)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from skills_engine.structured import (
    are_ranges_compatible,
    merge_docker_compose_services,
    merge_env_additions,
    merge_npm_dependencies,
)

if TYPE_CHECKING:
    from pathlib import Path


class TestAreRangesCompatible:
    def test_identical_versions_are_compatible(self) -> None:
        result = are_ranges_compatible("^1.0.0", "^1.0.0")
        assert result["compatible"] is True

    def test_compatible_caret_ranges_resolve_to_higher(self) -> None:
        result = are_ranges_compatible("^1.0.0", "^1.1.0")
        assert result["compatible"] is True
        assert result["resolved"] == "^1.1.0"

    def test_incompatible_major_caret_ranges(self) -> None:
        result = are_ranges_compatible("^1.0.0", "^2.0.0")
        assert result["compatible"] is False

    def test_compatible_tilde_ranges(self) -> None:
        result = are_ranges_compatible("~1.0.0", "~1.0.3")
        assert result["compatible"] is True
        assert result["resolved"] == "~1.0.3"

    def test_mismatched_prefixes_are_incompatible(self) -> None:
        result = are_ranges_compatible("^1.0.0", "~1.0.0")
        assert result["compatible"] is False

    def test_handles_double_digit_version_parts_numerically(self) -> None:
        # ^1.9.0 vs ^1.10.0 -- 10 > 9 numerically, but "9" > "10" as strings
        result = are_ranges_compatible("^1.9.0", "^1.10.0")
        assert result["compatible"] is True
        assert result["resolved"] == "^1.10.0"

    def test_handles_double_digit_patch_versions(self) -> None:
        result = are_ranges_compatible("~1.0.9", "~1.0.10")
        assert result["compatible"] is True
        assert result["resolved"] == "~1.0.10"


class TestMergeNpmDependencies:
    def test_adds_new_dependencies(self, skills_tmp: Path) -> None:
        pkg_path = skills_tmp / "package.json"
        pkg_path.write_text(
            json.dumps(
                {
                    "name": "test",
                    "dependencies": {"existing": "^1.0.0"},
                },
                indent=2,
            )
        )

        merge_npm_dependencies(pkg_path, {"newdep": "^2.0.0"})

        pkg = json.loads(pkg_path.read_text())
        assert pkg["dependencies"]["newdep"] == "^2.0.0"
        assert pkg["dependencies"]["existing"] == "^1.0.0"

    def test_resolves_compatible_caret_ranges(self, skills_tmp: Path) -> None:
        pkg_path = skills_tmp / "package.json"
        pkg_path.write_text(
            json.dumps(
                {
                    "name": "test",
                    "dependencies": {"dep": "^1.0.0"},
                },
                indent=2,
            )
        )

        merge_npm_dependencies(pkg_path, {"dep": "^1.1.0"})

        pkg = json.loads(pkg_path.read_text())
        assert pkg["dependencies"]["dep"] == "^1.1.0"

    def test_sorts_dev_dependencies_after_merge(self, skills_tmp: Path) -> None:
        pkg_path = skills_tmp / "package.json"
        pkg_path.write_text(
            json.dumps(
                {
                    "name": "test",
                    "dependencies": {},
                    "devDependencies": {"zlib": "^1.0.0", "acorn": "^2.0.0"},
                },
                indent=2,
            )
        )

        merge_npm_dependencies(pkg_path, {"middle": "^1.0.0"})

        pkg = json.loads(pkg_path.read_text())
        dev_keys = list(pkg["devDependencies"].keys())
        assert dev_keys == ["acorn", "zlib"]

    def test_throws_on_incompatible_major_versions(self, skills_tmp: Path) -> None:
        pkg_path = skills_tmp / "package.json"
        pkg_path.write_text(
            json.dumps(
                {
                    "name": "test",
                    "dependencies": {"dep": "^1.0.0"},
                },
                indent=2,
            )
        )

        with pytest.raises(ValueError):
            merge_npm_dependencies(pkg_path, {"dep": "^2.0.0"})


class TestMergeEnvAdditions:
    def test_adds_new_variables(self, skills_tmp: Path) -> None:
        env_path = skills_tmp / ".env.example"
        env_path.write_text("EXISTING_VAR=value\n")

        merge_env_additions(env_path, ["NEW_VAR"])

        content = env_path.read_text()
        assert "NEW_VAR=" in content
        assert "EXISTING_VAR=value" in content

    def test_skips_existing_variables(self, skills_tmp: Path) -> None:
        env_path = skills_tmp / ".env.example"
        env_path.write_text("MY_VAR=original\n")

        merge_env_additions(env_path, ["MY_VAR"])

        content = env_path.read_text()
        # Should not add duplicate - only 1 occurrence of MY_VAR=
        assert content.count("MY_VAR=") == 1

    def test_recognizes_lowercase_and_mixed_case_env_vars(self, skills_tmp: Path) -> None:
        env_path = skills_tmp / ".env.example"
        env_path.write_text("my_lower_var=value\nMixed_Case=abc\n")

        merge_env_additions(env_path, ["my_lower_var", "Mixed_Case"])

        content = env_path.read_text()
        assert content.count("my_lower_var=") == 1
        assert content.count("Mixed_Case=") == 1

    def test_creates_file_if_not_exists(self, skills_tmp: Path) -> None:
        env_path = skills_tmp / ".env.example"
        merge_env_additions(env_path, ["NEW_VAR"])

        assert env_path.exists()
        content = env_path.read_text()
        assert "NEW_VAR=" in content


class TestMergeDockerComposeServices:
    def test_adds_new_services(self, skills_tmp: Path) -> None:
        compose_path = skills_tmp / "docker-compose.yaml"
        compose_path.write_text('version: "3"\nservices:\n  web:\n    image: nginx\n')

        merge_docker_compose_services(
            compose_path,
            {
                "redis": {"image": "redis:7"},
            },
        )

        content = compose_path.read_text()
        assert "redis" in content

    def test_skips_existing_services(self, skills_tmp: Path) -> None:
        compose_path = skills_tmp / "docker-compose.yaml"
        compose_path.write_text('version: "3"\nservices:\n  web:\n    image: nginx\n')

        merge_docker_compose_services(
            compose_path,
            {
                "web": {"image": "apache"},
            },
        )

        content = compose_path.read_text()
        assert "nginx" in content

    def test_throws_on_port_collision(self, skills_tmp: Path) -> None:
        compose_path = skills_tmp / "docker-compose.yaml"
        compose_path.write_text('version: "3"\nservices:\n  web:\n    image: nginx\n    ports:\n      - "8080:80"\n')

        with pytest.raises(ValueError):
            merge_docker_compose_services(
                compose_path,
                {
                    "api": {"image": "node", "ports": ["8080:3000"]},
                },
            )
