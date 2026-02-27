"""Tests for group repository."""

import pytest

from g2.groups.types import ContainerConfig, RegisteredGroup
from g2.infrastructure.database import AppDatabase


@pytest.fixture
def group_repo():
    db = AppDatabase()
    db._init_test()
    return db.group_repo


def _group(name: str = "Test Group", folder: str = "test", trigger: str = "@G2") -> RegisteredGroup:
    return RegisteredGroup(
        name=name,
        folder=folder,
        trigger=trigger,
        added_at="2024-01-01T00:00:00",
        channel="whatsapp",
    )


class TestGroupRepository:
    def test_set_and_get(self, group_repo):
        group_repo.set_registered_group("test@g.us", _group())
        result = group_repo.get_registered_group("test@g.us")
        assert result is not None
        assert result.name == "Test Group"
        assert result.folder == "test"

    def test_get_nonexistent(self, group_repo):
        assert group_repo.get_registered_group("nonexistent@g.us") is None

    def test_get_all(self, group_repo):
        group_repo.set_registered_group("g1@g.us", _group(name="Group 1", folder="g1"))
        group_repo.set_registered_group("g2@g.us", _group(name="Group 2", folder="g2"))
        all_groups = group_repo.get_all_registered_groups()
        assert len(all_groups) == 2
        assert "g1@g.us" in all_groups
        assert "g2@g.us" in all_groups

    def test_upsert_overwrites(self, group_repo):
        group_repo.set_registered_group("test@g.us", _group(name="Old Name"))
        group_repo.set_registered_group("test@g.us", _group(name="New Name"))
        result = group_repo.get_registered_group("test@g.us")
        assert result.name == "New Name"

    def test_container_config_roundtrip(self, group_repo):
        group = _group()
        group.container_config = ContainerConfig(timeout=600000)
        group_repo.set_registered_group("test@g.us", group)
        result = group_repo.get_registered_group("test@g.us")
        assert result.container_config is not None
        assert result.container_config.timeout == 600000

    def test_dict_input_for_migrations(self, group_repo):
        group_repo.set_registered_group("test@g.us", {
            "name": "Migrated",
            "folder": "migrated",
            "trigger": "@G2",
            "added_at": "2024-01-01",
            "channel": "whatsapp",
        })
        result = group_repo.get_registered_group("test@g.us")
        assert result.name == "Migrated"

    def test_requires_trigger_default(self, group_repo):
        group_repo.set_registered_group("test@g.us", _group())
        result = group_repo.get_registered_group("test@g.us")
        assert result.requires_trigger is True
