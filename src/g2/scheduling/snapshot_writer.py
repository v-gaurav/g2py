"""Writes task, session, and groups snapshots for containers to read."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime

from g2.groups.paths import GroupPaths
from g2.scheduling.task_service import TaskManager


@dataclass
class AvailableGroup:
    jid: str
    name: str
    last_activity: str
    is_registered: bool


class SnapshotWriter:
    """Writes JSON snapshot files for container-visible state."""

    def __init__(self, task_manager: TaskManager) -> None:
        self._task_manager = task_manager

    def write_tasks(
        self,
        group_folder: str,
        is_main: bool,
        tasks: list[dict],
    ) -> None:
        """Write a filtered tasks snapshot for the container."""
        ipc_dir = GroupPaths.ipc_dir(group_folder)
        ipc_dir.mkdir(parents=True, exist_ok=True)

        filtered = tasks if is_main else [t for t in tasks if t.get("groupFolder") == group_folder]

        tasks_file = ipc_dir / "current_tasks.json"
        tasks_file.write_text(json.dumps(filtered, indent=2))

    def write_session_history(
        self,
        group_folder: str,
        sessions: list[dict],
    ) -> None:
        """Write session history snapshot."""
        ipc_dir = GroupPaths.ipc_dir(group_folder)
        ipc_dir.mkdir(parents=True, exist_ok=True)
        (ipc_dir / "session_history.json").write_text(json.dumps(sessions, indent=2))

    def write_groups(
        self,
        group_folder: str,
        is_main: bool,
        groups: list[AvailableGroup],
        _registered_jids: set[str],
    ) -> None:
        """Write available groups snapshot. Only main sees all groups."""
        ipc_dir = GroupPaths.ipc_dir(group_folder)
        ipc_dir.mkdir(parents=True, exist_ok=True)

        visible = [{"jid": g.jid, "name": g.name, "lastActivity": g.last_activity, "isRegistered": g.is_registered} for g in groups] if is_main else []

        (ipc_dir / "available_groups.json").write_text(
            json.dumps({"groups": visible, "lastSync": datetime.now().isoformat()}, indent=2)
        )

    def refresh_tasks(self, group_folder: str, is_main: bool) -> None:
        """Refresh tasks snapshot from the database."""
        tasks = self._task_manager.get_all()
        self.write_tasks(
            group_folder,
            is_main,
            [
                {
                    "id": t.id,
                    "groupFolder": t.group_folder,
                    "prompt": t.prompt,
                    "schedule_type": t.schedule_type,
                    "schedule_value": t.schedule_value,
                    "status": t.status,
                    "next_run": t.next_run,
                }
                for t in tasks
            ],
        )

    def prepare_for_execution(
        self,
        group_folder: str,
        is_main: bool,
        available_groups: list[AvailableGroup],
        registered_jids: set[str],
        conversation_archives: list[dict],
    ) -> None:
        """Prepare all snapshots for a container execution."""
        self.refresh_tasks(group_folder, is_main)
        self.write_groups(group_folder, is_main, available_groups, registered_jids)
        self.write_session_history(group_folder, conversation_archives)
