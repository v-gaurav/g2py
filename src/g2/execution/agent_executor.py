"""Agent executor — ties container execution to session tracking."""

from __future__ import annotations

from typing import Callable, Awaitable

from g2.execution.container_runner import ContainerInput, ContainerOutput, ContainerRunner
from g2.execution.execution_queue import GroupQueue
from g2.groups.types import RegisteredGroup
from g2.infrastructure.config import MAIN_GROUP_FOLDER
from g2.infrastructure.logger import logger
from g2.scheduling.snapshot_writer import AvailableGroup, SnapshotWriter
from g2.sessions.manager import SessionManager


class AgentExecutor:
    """Executes agent containers with session tracking and snapshot management."""

    def __init__(
        self,
        session_manager: SessionManager,
        queue: GroupQueue,
        get_available_groups: Callable[[], list[AvailableGroup]],
        get_registered_groups: Callable[[], dict[str, RegisteredGroup]],
        snapshot_writer: SnapshotWriter,
        container_runner: ContainerRunner,
    ) -> None:
        self._session_manager = session_manager
        self._queue = queue
        self._get_available_groups = get_available_groups
        self._get_registered_groups = get_registered_groups
        self._snapshot_writer = snapshot_writer
        self._container_runner = container_runner

    async def execute(
        self,
        group: RegisteredGroup,
        prompt: str,
        chat_jid: str,
        on_output: Callable[[ContainerOutput], Awaitable[None]] | None = None,
    ) -> str:
        """Execute an agent container. Returns 'success' or 'error'."""
        is_main = group.folder == MAIN_GROUP_FOLDER
        session_id = self._session_manager.get(group.folder)

        # Write all snapshots for the container to read
        available_groups = self._get_available_groups()
        archives = self._session_manager.get_archives(group.folder)
        self._snapshot_writer.prepare_for_execution(
            group.folder,
            is_main,
            available_groups,
            set(self._get_registered_groups().keys()),
            [{"id": s["id"], "name": s["name"], "session_id": s["session_id"], "archived_at": s["archived_at"]} for s in archives],
        )

        # Wrap onOutput to track session ID from streamed results
        async def wrapped_on_output(output: ContainerOutput) -> None:
            if output.new_session_id:
                self._session_manager.set(group.folder, output.new_session_id)
            if on_output:
                await on_output(output)

        try:
            output = await self._container_runner.run(
                group,
                ContainerInput(
                    prompt=prompt,
                    session_id=session_id,
                    group_folder=group.folder,
                    chat_jid=chat_jid,
                    is_main=is_main,
                ),
                on_process=lambda proc, name: self._queue.register_process(chat_jid, proc, name, group.folder),
                on_output=wrapped_on_output,
            )

            if output.new_session_id:
                self._session_manager.set(group.folder, output.new_session_id)

            if output.status == "error":
                logger.error("Container agent error", group=group.name, error=output.error)
                return "error"

            return "success"
        except Exception:
            logger.exception("Agent error", group=group.name)
            return "error"
