"""Centralized path construction for group-related directories and files."""

from __future__ import annotations

from pathlib import Path

from g2.infrastructure.config import DATA_DIR, GROUPS_DIR


class GroupPaths:
    """Centralized path construction for group-related directories."""

    @staticmethod
    def group_dir(folder: str) -> Path:
        """Root directory for a group: groups/{folder}"""
        return GROUPS_DIR / folder

    @staticmethod
    def logs_dir(folder: str) -> Path:
        """Logs directory: groups/{folder}/logs"""
        return GROUPS_DIR / folder / "logs"

    @staticmethod
    def ipc_dir(folder: str) -> Path:
        """IPC root directory: data/ipc/{folder}"""
        return DATA_DIR / "ipc" / folder

    @staticmethod
    def ipc_input_dir(folder: str) -> Path:
        """IPC input directory: data/ipc/{folder}/input"""
        return DATA_DIR / "ipc" / folder / "input"

    @staticmethod
    def ipc_messages_dir(folder: str) -> Path:
        """IPC messages directory: data/ipc/{folder}/messages"""
        return DATA_DIR / "ipc" / folder / "messages"

    @staticmethod
    def ipc_tasks_dir(folder: str) -> Path:
        """IPC tasks directory: data/ipc/{folder}/tasks"""
        return DATA_DIR / "ipc" / folder / "tasks"

    @staticmethod
    def ipc_responses_dir(folder: str) -> Path:
        """IPC responses directory: data/ipc/{folder}/responses"""
        return DATA_DIR / "ipc" / folder / "responses"

    @staticmethod
    def sessions_dir(folder: str) -> Path:
        """Sessions directory: data/sessions/{folder}/.claude"""
        return DATA_DIR / "sessions" / folder / ".claude"

    @staticmethod
    def session_transcript(folder: str, session_id: str) -> Path:
        """Session transcript path."""
        return DATA_DIR / "sessions" / folder / ".claude" / "projects" / "-workspace-group" / f"{session_id}.jsonl"
