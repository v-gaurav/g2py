"""Scheduled task CRUD, claiming, and run logging."""

from __future__ import annotations

import sqlite3
from datetime import datetime

from g2.scheduling.types import ScheduledTask, TaskRunLog


class TaskRepository:
    def __init__(self, db: sqlite3.Connection) -> None:
        self._db = db

    def create_task(self, task: ScheduledTask) -> None:
        self._db.execute(
            """INSERT INTO scheduled_tasks
               (id, group_folder, chat_jid, prompt, schedule_type, schedule_value, context_mode, next_run, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                task.id, task.group_folder, task.chat_jid, task.prompt,
                task.schedule_type, task.schedule_value, task.context_mode,
                task.next_run, task.status, task.created_at,
            ),
        )
        self._db.commit()

    def get_task_by_id(self, id: str) -> ScheduledTask | None:
        row = self._db.execute("SELECT * FROM scheduled_tasks WHERE id = ?", (id,)).fetchone()
        if not row:
            return None
        return self._row_to_task(row)

    def get_tasks_for_group(self, group_folder: str) -> list[ScheduledTask]:
        rows = self._db.execute(
            "SELECT * FROM scheduled_tasks WHERE group_folder = ? ORDER BY created_at DESC", (group_folder,)
        ).fetchall()
        return [self._row_to_task(row) for row in rows]

    def get_all_tasks(self) -> list[ScheduledTask]:
        rows = self._db.execute("SELECT * FROM scheduled_tasks ORDER BY created_at DESC").fetchall()
        return [self._row_to_task(row) for row in rows]

    def update_task(self, id: str, **updates: str | None) -> None:
        fields: list[str] = []
        values: list[str | None] = []
        for key, value in updates.items():
            if value is not None:
                fields.append(f"{key} = ?")
                values.append(value)
        if not fields:
            return
        values.append(id)
        self._db.execute(f"UPDATE scheduled_tasks SET {', '.join(fields)} WHERE id = ?", values)
        self._db.commit()

    def delete_task(self, id: str) -> None:
        self._db.execute("DELETE FROM task_run_logs WHERE task_id = ?", (id,))
        self._db.execute("DELETE FROM scheduled_tasks WHERE id = ?", (id,))
        self._db.commit()

    def get_due_tasks(self) -> list[ScheduledTask]:
        now = datetime.now().isoformat()
        rows = self._db.execute(
            """SELECT * FROM scheduled_tasks
               WHERE status = 'active' AND next_run IS NOT NULL AND next_run <= ?
               ORDER BY next_run""",
            (now,),
        ).fetchall()
        return [self._row_to_task(row) for row in rows]

    def claim_task(self, id: str) -> bool:
        result = self._db.execute(
            """UPDATE scheduled_tasks
               SET next_run = NULL
               WHERE id = ? AND status = 'active' AND next_run IS NOT NULL""",
            (id,),
        )
        self._db.commit()
        return result.rowcount > 0

    def update_task_after_run(self, id: str, next_run: str | None, last_result: str) -> None:
        now = datetime.now().isoformat()
        self._db.execute(
            """UPDATE scheduled_tasks
               SET next_run = ?, last_run = ?, last_result = ?,
                   status = CASE WHEN ? IS NULL THEN 'completed' ELSE status END
               WHERE id = ?""",
            (next_run, now, last_result, next_run, id),
        )
        self._db.commit()

    def log_task_run(self, log: TaskRunLog) -> None:
        self._db.execute(
            """INSERT INTO task_run_logs (task_id, run_at, duration_ms, status, result, error)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (log.task_id, log.run_at, log.duration_ms, log.status, log.result, log.error),
        )
        self._db.commit()

    def _row_to_task(self, row: sqlite3.Row) -> ScheduledTask:
        return ScheduledTask(
            id=row["id"],
            group_folder=row["group_folder"],
            chat_jid=row["chat_jid"],
            prompt=row["prompt"],
            schedule_type=row["schedule_type"],
            schedule_value=row["schedule_value"],
            context_mode=row["context_mode"] if "context_mode" in row.keys() else "isolated",
            next_run=row["next_run"],
            last_run=row["last_run"],
            last_result=row["last_result"],
            status=row["status"],
            created_at=row["created_at"],
        )
