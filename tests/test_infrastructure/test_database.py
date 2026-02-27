"""Tests for database initialization and schema."""

from g2.infrastructure.database import AppDatabase


class TestAppDatabase:
    def test_init_creates_schema(self):
        db = AppDatabase()
        db._init_test()
        # Verify tables exist by querying them
        tables = db.db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        table_names = [row[0] for row in tables]
        assert "chats" in table_names
        assert "messages" in table_names
        assert "scheduled_tasks" in table_names
        assert "task_run_logs" in table_names
        assert "sessions" in table_names
        assert "registered_groups" in table_names
        assert "conversation_archives" in table_names
        assert "router_state" in table_names

    def test_repos_initialized(self):
        db = AppDatabase()
        db._init_test()
        assert db.message_repo is not None
        assert db.task_repo is not None
        assert db.session_repo is not None
        assert db.group_repo is not None
        assert db.state_repo is not None

    def test_multiple_init_is_safe(self):
        db = AppDatabase()
        db._init_test()
        db._init_test()  # Should not raise


class TestStateRepo:
    def test_set_and_get(self):
        db = AppDatabase()
        db._init_test()
        db.state_repo.set_router_state("key1", "value1")
        assert db.state_repo.get_router_state("key1") == "value1"

    def test_get_nonexistent(self):
        db = AppDatabase()
        db._init_test()
        assert db.state_repo.get_router_state("nonexistent") is None

    def test_upsert(self):
        db = AppDatabase()
        db._init_test()
        db.state_repo.set_router_state("key1", "old")
        db.state_repo.set_router_state("key1", "new")
        assert db.state_repo.get_router_state("key1") == "new"
