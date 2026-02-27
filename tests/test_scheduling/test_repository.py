"""Tests for task repository."""

import pytest

from g2.infrastructure.database import AppDatabase
from g2.scheduling.types import ScheduledTask, TaskRunLog


@pytest.fixture
def task_repo():
    db = AppDatabase()
    db._init_test()
    return db.task_repo


def _task(id: str = "task-1", group_folder: str = "main", status: str = "active", next_run: str | None = "2024-01-01T00:00:00") -> ScheduledTask:
    return ScheduledTask(
        id=id,
        group_folder=group_folder,
        chat_jid="test@g.us",
        prompt="Test prompt",
        schedule_type="once",
        schedule_value="2024-01-01T00:00:00",
        next_run=next_run,
        status=status,
        created_at="2024-01-01T00:00:00",
    )


class TestTaskCRUD:
    def test_create_and_get(self, task_repo):
        task_repo.create_task(_task())
        result = task_repo.get_task_by_id("task-1")
        assert result is not None
        assert result.prompt == "Test prompt"

    def test_get_nonexistent(self, task_repo):
        assert task_repo.get_task_by_id("nonexistent") is None

    def test_update(self, task_repo):
        task_repo.create_task(_task())
        task_repo.update_task("task-1", status="paused")
        result = task_repo.get_task_by_id("task-1")
        assert result.status == "paused"

    def test_delete(self, task_repo):
        task_repo.create_task(_task())
        task_repo.delete_task("task-1")
        assert task_repo.get_task_by_id("task-1") is None

    def test_get_tasks_for_group(self, task_repo):
        task_repo.create_task(_task(id="t1", group_folder="main"))
        task_repo.create_task(_task(id="t2", group_folder="other"))
        results = task_repo.get_tasks_for_group("main")
        assert len(results) == 1
        assert results[0].id == "t1"

    def test_get_all_tasks(self, task_repo):
        task_repo.create_task(_task(id="t1"))
        task_repo.create_task(_task(id="t2"))
        assert len(task_repo.get_all_tasks()) == 2


class TestTaskClaim:
    def test_claim_sets_next_run_null(self, task_repo):
        task_repo.create_task(_task())
        assert task_repo.claim_task("task-1") is True
        result = task_repo.get_task_by_id("task-1")
        assert result.next_run is None

    def test_double_claim_fails(self, task_repo):
        task_repo.create_task(_task())
        assert task_repo.claim_task("task-1") is True
        assert task_repo.claim_task("task-1") is False

    def test_claim_paused_task_fails(self, task_repo):
        task_repo.create_task(_task(status="paused"))
        assert task_repo.claim_task("task-1") is False


class TestDueTasks:
    def test_returns_due_tasks(self, task_repo):
        task_repo.create_task(_task(id="due", next_run="2020-01-01T00:00:00"))
        task_repo.create_task(_task(id="future", next_run="2099-01-01T00:00:00"))
        due = task_repo.get_due_tasks()
        ids = [t.id for t in due]
        assert "due" in ids
        assert "future" not in ids

    def test_excludes_paused(self, task_repo):
        task_repo.create_task(_task(status="paused", next_run="2020-01-01T00:00:00"))
        assert len(task_repo.get_due_tasks()) == 0

    def test_excludes_null_next_run(self, task_repo):
        task_repo.create_task(_task(next_run=None))
        assert len(task_repo.get_due_tasks()) == 0


class TestRunLogging:
    def test_log_run(self, task_repo):
        task_repo.create_task(_task())
        task_repo.log_task_run(TaskRunLog(
            task_id="task-1",
            run_at="2024-01-01T00:00:00",
            duration_ms=1000,
            status="success",
            result="Done",
        ))
        # Verify by checking the task still exists (logs don't delete tasks)
        assert task_repo.get_task_by_id("task-1") is not None

    def test_update_after_run(self, task_repo):
        task_repo.create_task(_task())
        task_repo.update_task_after_run("task-1", None, "Completed")
        result = task_repo.get_task_by_id("task-1")
        assert result.status == "completed"
        assert result.last_result == "Completed"

    def test_update_after_run_with_next(self, task_repo):
        task_repo.create_task(_task())
        task_repo.update_task_after_run("task-1", "2024-02-01T00:00:00", "Done")
        result = task_repo.get_task_by_id("task-1")
        assert result.status == "active"  # Not completed because next_run is set
        assert result.next_run == "2024-02-01T00:00:00"
