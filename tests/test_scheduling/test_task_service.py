"""Tests for task service."""

import pytest

from g2.infrastructure.database import AppDatabase
from g2.scheduling.task_service import TaskManager


@pytest.fixture
def task_manager():
    db = AppDatabase()
    db._init_test()
    return TaskManager(db.task_repo)


class TestTaskCreate:
    def test_creates_task(self, task_manager):
        task_id = task_manager.create("main", "test@g.us", "Say hello", "once", "2099-01-01T00:00:00")
        assert task_id.startswith("task-")
        task = task_manager.get_by_id(task_id)
        assert task is not None
        assert task.prompt == "Say hello"
        assert task.schedule_type == "once"

    def test_creates_cron_task(self, task_manager):
        task_id = task_manager.create("main", "test@g.us", "Daily check", "cron", "0 9 * * *")
        task = task_manager.get_by_id(task_id)
        assert task.schedule_type == "cron"
        assert task.next_run is not None

    def test_creates_interval_task(self, task_manager):
        task_id = task_manager.create("main", "test@g.us", "Periodic", "interval", "60000")
        task = task_manager.get_by_id(task_id)
        assert task.schedule_type == "interval"
        assert task.next_run is not None

    def test_invalid_cron(self, task_manager):
        with pytest.raises(ValueError, match="Invalid cron"):
            task_manager.create("main", "test@g.us", "Bad", "cron", "invalid cron")

    def test_invalid_interval(self, task_manager):
        with pytest.raises(ValueError, match="Invalid interval"):
            task_manager.create("main", "test@g.us", "Bad", "interval", "not-a-number")

    def test_negative_interval(self, task_manager):
        with pytest.raises(ValueError, match="Invalid interval"):
            task_manager.create("main", "test@g.us", "Bad", "interval", "-1000")


class TestTaskLifecycle:
    def test_pause_and_resume(self, task_manager):
        task_id = task_manager.create("main", "test@g.us", "Test", "once", "2099-01-01T00:00:00")
        task_manager.pause(task_id)
        task = task_manager.get_by_id(task_id)
        assert task.status == "paused"

        task_manager.resume(task_id)
        task = task_manager.get_by_id(task_id)
        assert task.status == "active"

    def test_cancel(self, task_manager):
        task_id = task_manager.create("main", "test@g.us", "Test", "once", "2099-01-01T00:00:00")
        task_manager.cancel(task_id)
        assert task_manager.get_by_id(task_id) is None


class TestTaskRetrieval:
    def test_get_all(self, task_manager):
        task_manager.create("main", "test@g.us", "Task 1", "once", "2099-01-01T00:00:00")
        task_manager.create("other", "test@g.us", "Task 2", "once", "2099-01-01T00:00:00")
        all_tasks = task_manager.get_all()
        assert len(all_tasks) == 2

    def test_get_for_group(self, task_manager):
        task_manager.create("main", "test@g.us", "Task 1", "once", "2099-01-01T00:00:00")
        task_manager.create("other", "test@g.us", "Task 2", "once", "2099-01-01T00:00:00")
        main_tasks = task_manager.get_for_group("main")
        assert len(main_tasks) == 1
        assert main_tasks[0].prompt == "Task 1"

    def test_get_nonexistent(self, task_manager):
        assert task_manager.get_by_id("nonexistent") is None


class TestTaskAuthorization:
    def test_main_can_manage_any_task(self, task_manager):
        task_id = task_manager.create("other", "test@g.us", "Test", "once", "2099-01-01T00:00:00")
        task = task_manager.get_authorized(task_id, "main", is_main=True)
        assert task is not None

    def test_non_main_can_manage_own_task(self, task_manager):
        task_id = task_manager.create("project-a", "test@g.us", "Test", "once", "2099-01-01T00:00:00")
        task = task_manager.get_authorized(task_id, "project-a", is_main=False)
        assert task is not None

    def test_non_main_cannot_manage_other_task(self, task_manager):
        task_id = task_manager.create("project-a", "test@g.us", "Test", "once", "2099-01-01T00:00:00")
        with pytest.raises(PermissionError):
            task_manager.get_authorized(task_id, "project-b", is_main=False)

    def test_nonexistent_task_raises(self, task_manager):
        with pytest.raises(ValueError, match="Task not found"):
            task_manager.get_authorized("nonexistent", "main", is_main=True)


class TestDueTasks:
    def test_due_task_found(self, task_manager):
        # Create a task with past next_run
        task_id = task_manager.create("main", "test@g.us", "Due", "once", "2020-01-01T00:00:00")
        due = task_manager.get_due_tasks()
        assert any(t.id == task_id for t in due)

    def test_future_task_not_due(self, task_manager):
        task_id = task_manager.create("main", "test@g.us", "Future", "once", "2099-01-01T00:00:00")
        due = task_manager.get_due_tasks()
        assert not any(t.id == task_id for t in due)

    def test_claim_prevents_double_execution(self, task_manager):
        task_id = task_manager.create("main", "test@g.us", "Due", "once", "2020-01-01T00:00:00")
        assert task_manager.claim(task_id) is True
        assert task_manager.claim(task_id) is False  # Already claimed
