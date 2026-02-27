"""Fine-grained authorization policy."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class AuthContext:
    source_group: str
    is_main: bool


class AuthorizationPolicy:
    """Encapsulates authorization checks for a single source context."""

    def __init__(self, ctx: AuthContext) -> None:
        self._ctx = ctx

    @property
    def source_group(self) -> str:
        return self._ctx.source_group

    @property
    def is_main(self) -> bool:
        return self._ctx.is_main

    def can_send_message(self, target_group_folder: str) -> bool:
        """Non-main groups can only send messages to their own group."""
        return self._ctx.is_main or target_group_folder == self._ctx.source_group

    def can_schedule_task(self, target_group_folder: str) -> bool:
        """Non-main groups can only schedule tasks for their own group."""
        return self._ctx.is_main or target_group_folder == self._ctx.source_group

    def can_manage_task(self, task_group_folder: str) -> bool:
        """Non-main groups can only manage their own tasks."""
        return self._ctx.is_main or task_group_folder == self._ctx.source_group

    def can_register_group(self) -> bool:
        """Only main group can register new groups."""
        return self._ctx.is_main

    def can_refresh_groups(self) -> bool:
        """Only main group can refresh/sync groups."""
        return self._ctx.is_main

    def can_manage_session(self, target_group_folder: str) -> bool:
        """Non-main groups can only manage their own sessions."""
        return self._ctx.is_main or target_group_folder == self._ctx.source_group
