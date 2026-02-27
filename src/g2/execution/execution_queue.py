"""Per-group queue with global concurrency limit using asyncio."""

from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass, field
from typing import Callable, Awaitable

from g2.infrastructure.config import MAX_CONCURRENT_CONTAINERS
from g2.infrastructure.logger import logger
from g2.ipc.transport import IpcTransport

MAX_RETRIES = 5
BASE_RETRY_S = 5.0


@dataclass
class QueuedTask:
    id: str
    group_jid: str
    fn: Callable[[], Awaitable[None]]


@dataclass
class GroupState:
    active: bool = False
    pending_messages: bool = False
    pending_tasks: list[QueuedTask] = field(default_factory=list)
    process: asyncio.subprocess.Process | None = None
    container_name: str | None = None
    group_folder: str | None = None
    retry_count: int = 0


class GroupQueue:
    """Per-group execution queue with global concurrency limiting."""

    def __init__(self, transport: IpcTransport | None = None) -> None:
        self._groups: dict[str, GroupState] = {}
        self._active_count = 0
        self._waiting_groups: set[str] = set()
        self._process_messages_fn: Callable[[str], Awaitable[bool]] | None = None
        self._shutting_down = False
        self._transport = transport or IpcTransport()

    def _get_group(self, group_jid: str) -> GroupState:
        state = self._groups.get(group_jid)
        if not state:
            state = GroupState()
            self._groups[group_jid] = state
        return state

    def set_process_messages_fn(self, fn: Callable[[str], Awaitable[bool]]) -> None:
        self._process_messages_fn = fn

    def enqueue_message_check(self, group_jid: str) -> None:
        if self._shutting_down:
            return

        state = self._get_group(group_jid)

        if state.active:
            state.pending_messages = True
            logger.debug("Container active, message queued", group_jid=group_jid)
            return

        if self._active_count >= MAX_CONCURRENT_CONTAINERS:
            state.pending_messages = True
            self._waiting_groups.add(group_jid)
            logger.debug("At concurrency limit, message queued", group_jid=group_jid, active=self._active_count)
            return

        asyncio.create_task(self._run_for_group(group_jid, "messages"))

    def enqueue_task(self, group_jid: str, task_id: str, fn: Callable[[], Awaitable[None]]) -> None:
        if self._shutting_down:
            return

        state = self._get_group(group_jid)

        if any(t.id == task_id for t in state.pending_tasks):
            logger.debug("Task already queued, skipping", group_jid=group_jid, task_id=task_id)
            return

        if state.active:
            state.pending_tasks.append(QueuedTask(id=task_id, group_jid=group_jid, fn=fn))
            self.close_stdin(group_jid)
            logger.debug("Container active, task queued — closing idle container", group_jid=group_jid, task_id=task_id)
            return

        if self._active_count >= MAX_CONCURRENT_CONTAINERS:
            state.pending_tasks.append(QueuedTask(id=task_id, group_jid=group_jid, fn=fn))
            self._waiting_groups.add(group_jid)
            logger.debug("At concurrency limit, task queued", group_jid=group_jid, task_id=task_id)
            return

        asyncio.create_task(self._run_task(group_jid, QueuedTask(id=task_id, group_jid=group_jid, fn=fn)))

    def register_process(
        self,
        group_jid: str,
        proc: asyncio.subprocess.Process,
        container_name: str,
        group_folder: str | None = None,
    ) -> None:
        state = self._get_group(group_jid)
        state.process = proc
        state.container_name = container_name
        if group_folder:
            state.group_folder = group_folder

    def send_message(self, group_jid: str, text: str) -> bool:
        state = self._get_group(group_jid)
        if not state.active or not state.group_folder:
            return False
        return self._transport.send_message(state.group_folder, text)

    def close_stdin(self, group_jid: str) -> None:
        state = self._get_group(group_jid)
        if not state.active or not state.group_folder:
            return
        self._transport.close_stdin(state.group_folder)

    async def _run_for_group(self, group_jid: str, reason: str) -> None:
        state = self._get_group(group_jid)
        state.active = True
        state.pending_messages = False
        self._active_count += 1

        logger.debug("Starting container for group", group_jid=group_jid, reason=reason, active=self._active_count)

        try:
            if self._process_messages_fn:
                success = await self._process_messages_fn(group_jid)
                if success:
                    state.retry_count = 0
                else:
                    self._schedule_retry(group_jid, state)
        except Exception:
            logger.exception("Error processing messages for group", group_jid=group_jid)
            self._schedule_retry(group_jid, state)
        finally:
            state.active = False
            state.process = None
            state.container_name = None
            state.group_folder = None
            self._active_count -= 1
            self._drain_group(group_jid)

    async def _run_task(self, group_jid: str, task: QueuedTask) -> None:
        state = self._get_group(group_jid)
        state.active = True
        self._active_count += 1

        logger.debug("Running queued task", group_jid=group_jid, task_id=task.id, active=self._active_count)

        try:
            await task.fn()
        except Exception:
            logger.exception("Error running task", group_jid=group_jid, task_id=task.id)
        finally:
            state.active = False
            state.process = None
            state.container_name = None
            state.group_folder = None
            self._active_count -= 1
            self._drain_group(group_jid)

    def _schedule_retry(self, group_jid: str, state: GroupState) -> None:
        state.retry_count += 1
        if state.retry_count > MAX_RETRIES:
            logger.error(
                "Max retries exceeded, dropping messages",
                group_jid=group_jid,
                retry_count=state.retry_count,
            )
            state.retry_count = 0
            return

        delay_s = BASE_RETRY_S * math.pow(2, state.retry_count - 1)
        logger.info("Scheduling retry with backoff", group_jid=group_jid, retry_count=state.retry_count, delay_s=delay_s)

        async def retry_later() -> None:
            await asyncio.sleep(delay_s)
            if not self._shutting_down:
                self.enqueue_message_check(group_jid)

        asyncio.create_task(retry_later())

    def _drain_group(self, group_jid: str) -> None:
        if self._shutting_down:
            return

        state = self._get_group(group_jid)

        # Tasks first (they won't be re-discovered from SQLite like messages)
        if state.pending_tasks:
            task = state.pending_tasks.pop(0)
            asyncio.create_task(self._run_task(group_jid, task))
            return

        if state.pending_messages:
            asyncio.create_task(self._run_for_group(group_jid, "drain"))
            return

        self._drain_waiting()

    def _drain_waiting(self) -> None:
        for next_jid in list(self._waiting_groups):
            if self._active_count >= MAX_CONCURRENT_CONTAINERS:
                break

            self._waiting_groups.discard(next_jid)
            state = self._get_group(next_jid)

            if state.pending_tasks:
                task = state.pending_tasks.pop(0)
                asyncio.create_task(self._run_task(next_jid, task))
            elif state.pending_messages:
                asyncio.create_task(self._run_for_group(next_jid, "drain"))

    async def shutdown(self, grace_period_s: float = 5.0) -> None:
        self._shutting_down = True

        active_containers: list[str] = []
        for _jid, state in self._groups.items():
            if state.process and state.container_name:
                try:
                    if state.process.returncode is None:
                        active_containers.append(state.container_name)
                except Exception:
                    pass

        logger.info(
            "GroupQueue shutting down (containers detached, not killed)",
            active_count=self._active_count,
            detached_containers=active_containers,
        )
