"""Tests for the constants module."""

from __future__ import annotations

from pathlib import Path

from skills_engine.constants import (
    BACKUP_DIR,
    BASE_DIR,
    CUSTOM_DIR,
    G2_DIR,
    LOCK_FILE,
    RESOLUTIONS_DIR,
    SKILLS_SCHEMA_VERSION,
    STATE_FILE,
)


class TestConstants:
    def test_all_constants_are_truthy(self) -> None:
        all_constants = {
            "G2_DIR": G2_DIR,
            "STATE_FILE": STATE_FILE,
            "BASE_DIR": BASE_DIR,
            "BACKUP_DIR": BACKUP_DIR,
            "LOCK_FILE": LOCK_FILE,
            "CUSTOM_DIR": CUSTOM_DIR,
            "RESOLUTIONS_DIR": RESOLUTIONS_DIR,
            "SKILLS_SCHEMA_VERSION": SKILLS_SCHEMA_VERSION,
        }
        for name, value in all_constants.items():
            assert value, f"{name} should be truthy"

    def test_path_constants_use_g2_prefix(self) -> None:
        path_constants = [BASE_DIR, BACKUP_DIR, LOCK_FILE, CUSTOM_DIR, RESOLUTIONS_DIR]
        for p in path_constants:
            p_str = str(p)
            assert "\\" not in p_str
            assert p_str.startswith(".g2/"), f"{p_str} should start with .g2/"

    def test_g2_dir_is_dot_g2(self) -> None:
        assert Path(".g2") == G2_DIR
