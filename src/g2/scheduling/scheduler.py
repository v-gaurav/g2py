"""Task scheduler — polls for due tasks and enqueues them."""

from __future__ import annotations

import asyncio
import time
from typing import Callable, Awaitable

from g2.execution.container_runner import ContainerInput, ContainerOutput, ContainerRunner
from g2.execution.execution_queue import GroupQueue
from g2.groups.paths import GroupPaths
from g2.groups.types import RegisteredGroup
from g2.infrastructure.config import IDLE_TIMEOUT, MAIN_GROUP_FOLDER, SCHEDULER_POLL_INTERVAL
from g2.infrastructure.idle_timer import IdleTimer
from g2.infrastructure.logger import logger
from g2.infrastructure.poll_loop import PollLoop, start_poll_loop
from g2.scheduling.snapshot_writer import SnapshotWriter
from g2.scheduling.task_service import TaskManager
from g2.scheduling.types import ScheduledTask


class SchedulerDependencies:
    def __init__(
        self,
        registered_groups: Callable[[], dict[str, RegisteredGroup]],
        get_sessions: Callable[[], dict[str, str]],
        queue: GroupQueue,
        send_message: Callable[[str, str], Awaitable[None]],
        task_manager: TaskManager,
        snapshot_writer: SnapshotWriter,
        container_runner: ContainerRunner,
    ) -> None:
        self.registered_groups = registered_groups
        self.get_sessions = get_sessions
        self.queue = queue
        self.send_message = send_message
        self.task_manager = task_manager
        self.snapshot_writer = snapshot_writer
        self.container_runner = container_runner


async def run_task(task: ScheduledTask, deps: SchedulerDependencies) -> None:
    """Run a single scheduled task in a container."""
    start_time = time.time()
    group_dir = GroupPaths.group_dir(task.group_folder)
    group_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Running scheduled task", task_id=task.id, group=task.group_folder)

    groups = deps.registered_groups()
    group = next((g for g in groups.values() if g.folder == task.group_folder), None)

    if not group:
        logger.error("Group not found for task", task_id=task.id, group_folder=task.group_folder)
        deps.task_manager.complete_run(task, int((time.time() - start_time) * 1000), None, f"Group not found: {task.group_folder}")
        return

    is_main = task.group_folder == MAIN_GROUP_FOLDER
    deps.snapshot_writer.refresh_tasks(task.group_folder, is_main)

    result: str | None = None
    error: str | None = None

    sessions = deps.get_sessions()
    session_id = sessions.get(task.group_folder) if task.context_mode == "group" else None

    idle = IdleTimer(
        lambda: (logger.debug("Scheduled task idle timeout", task_id=task.id), deps.queue.close_stdin(task.chat_jid)),
        IDLE_TIMEOUT / 1000,
    )

    try:
        output = await deps.container_runner.run(
            group,
            ContainerInput(
                prompt=task.prompt,
                session_id=session_id,
                group_folder=task.group_folder,
                chat_jid=task.chat_jid,
                is_main=is_main,
                is_scheduled_task=True,
            ),
            on_process=lambda proc, name: deps.queue.register_process(task.chat_jid, proc, name, task.group_folder),
            on_output=_make_output_handler(task, deps, idle, result_holder := [None], error_holder := [None]),
        )

        idle.clear()
        result = result_holder[0]
        error = error_holder[0]

        if output.status == "error":
            error = output.error or "Unknown error"
        elif output.result:
            result = output.result

        logger.info("Task completed", task_id=task.id, duration_ms=int((time.time() - start_time) * 1000))
    except Exception as err:
        idle.clear()
        error = str(err)
        logger.error("Task failed", task_id=task.id, error=error)

    duration_ms = int((time.time() - start_time) * 1000)
    deps.task_manager.complete_run(task, duration_ms, result, error)


def _make_output_handler(
    task: ScheduledTask,
    deps: SchedulerDependencies,
    idle: IdleTimer,
    result_holder: list,
    error_holder: list,
) -> Callable[[ContainerOutput], Awaitable[None]]:
    async def handler(streamed_output: ContainerOutput) -> None:
        if streamed_output.result:
            result_holder[0] = streamed_output.result
            await deps.send_message(task.chat_jid, streamed_output.result)
            idle.reset()
        if streamed_output.status == "error":
            error_holder[0] = streamed_output.error or "Unknown error"

    return handler


def start_scheduler_loop(deps: SchedulerDependencies) -> PollLoop:
    """Start the scheduler polling loop."""

    async def poll() -> None:
        due_tasks = deps.task_manager.get_due_tasks()
        if due_tasks:
            logger.info("Found due tasks", count=len(due_tasks))

        for task in due_tasks:
            if not deps.task_manager.claim(task.id):
                continue
            deps.queue.enqueue_task(task.chat_jid, task.id, lambda t=task: run_task(t, deps))

    return start_poll_loop("Scheduler", SCHEDULER_POLL_INTERVAL, poll)
