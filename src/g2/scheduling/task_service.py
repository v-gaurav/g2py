"""Task manager — centralized task lifecycle."""

from __future__ import annotations

import time
import random
import string
from datetime import datetime

from croniter import croniter

from g2.groups.authorization import AuthContext, AuthorizationPolicy
from g2.infrastructure.config import TIMEZONE
from g2.scheduling.repository import TaskRepository
from g2.scheduling.types import ScheduledTask, TaskRunLog


class TaskManager:
    def __init__(self, task_repo: TaskRepository) -> None:
        self._task_repo = task_repo

    # --- CRUD ---

    def create(
        self,
        group_folder: str,
        chat_jid: str,
        prompt: str,
        schedule_type: str,
        schedule_value: str,
        context_mode: str = "isolated",
    ) -> str:
        next_run = self.compute_next_run(schedule_type, schedule_value)
        rand = "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
        task_id = f"task-{int(time.time())}-{rand}"

        task = ScheduledTask(
            id=task_id,
            group_folder=group_folder,
            chat_jid=chat_jid,
            prompt=prompt,
            schedule_type=schedule_type,  # type: ignore[arg-type]
            schedule_value=schedule_value,
            context_mode=context_mode,  # type: ignore[arg-type]
            next_run=next_run,
            status="active",
            created_at=datetime.now().isoformat(),
        )
        self._task_repo.create_task(task)
        return task_id

    def get_by_id(self, id: str) -> ScheduledTask | None:
        return self._task_repo.get_task_by_id(id)

    def get_all(self) -> list[ScheduledTask]:
        return self._task_repo.get_all_tasks()

    def get_for_group(self, group_folder: str) -> list[ScheduledTask]:
        return self._task_repo.get_tasks_for_group(group_folder)

    # --- Lifecycle ---

    def pause(self, id: str) -> None:
        self._task_repo.update_task(id, status="paused")

    def resume(self, id: str) -> None:
        self._task_repo.update_task(id, status="active")

    def cancel(self, id: str) -> None:
        self._task_repo.delete_task(id)

    # --- Scheduling ---

    def get_due_tasks(self) -> list[ScheduledTask]:
        return self._task_repo.get_due_tasks()

    def claim(self, id: str) -> bool:
        return self._task_repo.claim_task(id)

    def complete_run(
        self, task: ScheduledTask, duration_ms: int, result: str | None, error: str | None
    ) -> None:
        self._task_repo.log_task_run(TaskRunLog(
            task_id=task.id,
            run_at=datetime.now().isoformat(),
            duration_ms=duration_ms,
            status="error" if error else "success",
            result=result,
            error=error,
        ))

        next_run = self._compute_next_run_after_execution(task)
        result_summary = f"Error: {error}" if error else (result[:200] if result else "Completed")
        self._task_repo.update_task_after_run(task.id, next_run, result_summary)

    # --- Authorization ---

    def get_authorized(self, task_id: str, source_group: str, is_main: bool) -> ScheduledTask:
        task = self._task_repo.get_task_by_id(task_id)
        if not task:
            raise ValueError(f"Task not found: {task_id}")
        auth = AuthorizationPolicy(AuthContext(source_group=source_group, is_main=is_main))
        if not auth.can_manage_task(task.group_folder):
            raise PermissionError(f"Unauthorized task management: {task_id}")
        return task

    # --- Internal ---

    def compute_next_run(self, schedule_type: str, schedule_value: str) -> str | None:
        if schedule_type == "cron":
            try:
                cron = croniter(schedule_value, datetime.now())
                return cron.get_next(datetime).isoformat()
            except (ValueError, KeyError):
                raise ValueError(f"Invalid cron expression: {schedule_value}")
        elif schedule_type == "interval":
            try:
                ms = int(schedule_value)
                if ms <= 0:
                    raise ValueError()
            except (ValueError, TypeError):
                raise ValueError(f"Invalid interval: {schedule_value}")
            return datetime.fromtimestamp(time.time() + ms / 1000).isoformat()
        elif schedule_type == "once":
            try:
                scheduled = datetime.fromisoformat(schedule_value)
                return scheduled.isoformat()
            except ValueError:
                raise ValueError(f"Invalid timestamp: {schedule_value}")
        return None

    def _compute_next_run_after_execution(self, task: ScheduledTask) -> str | None:
        if task.schedule_type == "cron":
            cron = croniter(task.schedule_value, datetime.now())
            return cron.get_next(datetime).isoformat()
        elif task.schedule_type == "interval":
            ms = int(task.schedule_value)
            return datetime.fromtimestamp(time.time() + ms / 1000).isoformat()
        return None
