"""IPC watcher — watches IPC directory for commands from containers."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Callable, Awaitable

from g2.groups.authorization import AuthContext, AuthorizationPolicy
from g2.groups.paths import GroupPaths
from g2.groups.types import RegisteredGroup
from g2.infrastructure.config import DATA_DIR, IPC_POLL_INTERVAL, MAIN_GROUP_FOLDER
from g2.infrastructure.logger import logger
from g2.ipc.dispatcher import IpcCommandDispatcher
from g2.ipc.handlers.group_handlers import RefreshGroupsHandler, RegisterGroupHandler
from g2.ipc.handlers.session_handlers import (
    ArchiveSessionHandler,
    ClearSessionHandler,
    ResumeSessionHandler,
    SearchSessionsHandler,
)
from g2.ipc.handlers.task_handlers import (
    CancelTaskHandler,
    PauseTaskHandler,
    ResumeTaskHandler,
    ScheduleTaskHandler,
)
from g2.scheduling.snapshot_writer import AvailableGroup
from g2.scheduling.task_service import TaskManager
from g2.sessions.manager import SessionManager


class IpcDeps:
    """Dependencies for IPC handlers, passed as a context object."""

    def __init__(
        self,
        send_message: Callable[[str, str], Awaitable[None]],
        send_media: Callable[[str, str, str, str | None, str | None], Awaitable[None]] | None,
        registered_groups: Callable[[], dict[str, RegisteredGroup]],
        register_group: Callable[[str, RegisteredGroup], None],
        sync_group_metadata: Callable[[bool], Awaitable[None]],
        get_available_groups: Callable[[], list[AvailableGroup]],
        write_groups_snapshot: Callable[[str, bool, list[AvailableGroup], set[str]], None],
        session_manager: SessionManager,
        close_stdin: Callable[[str], None],
        task_manager: TaskManager,
    ) -> None:
        self.send_message = send_message
        self.send_media = send_media
        self.registered_groups = registered_groups
        self.register_group = register_group
        self.sync_group_metadata = sync_group_metadata
        self.get_available_groups = get_available_groups
        self.write_groups_snapshot = write_groups_snapshot
        self.session_manager = session_manager
        self.close_stdin = close_stdin
        self.task_manager = task_manager


# Fallback poll interval: slower since watchfiles handles the fast path
FALLBACK_POLL_INTERVAL = IPC_POLL_INTERVAL * 10


class IpcWatcher:
    """Watches the IPC directory tree for commands from containers."""

    def __init__(self) -> None:
        self._dispatcher = IpcCommandDispatcher([
            ScheduleTaskHandler(),
            PauseTaskHandler(),
            ResumeTaskHandler(),
            CancelTaskHandler(),
            RefreshGroupsHandler(),
            RegisterGroupHandler(),
            ClearSessionHandler(),
            ResumeSessionHandler(),
            SearchSessionsHandler(),
            ArchiveSessionHandler(),
        ])
        self._ipc_base_dir = DATA_DIR / "ipc"
        self._processing = False
        self._running = False
        self._watch_task: asyncio.Task | None = None
        self._poll_task: asyncio.Task | None = None

    def start(self, deps: IpcDeps) -> None:
        if self._running:
            logger.debug("IPC watcher already running, skipping duplicate start")
            return
        self._running = True
        self._ipc_base_dir.mkdir(parents=True, exist_ok=True)

        # Try to use watchfiles for event-driven processing
        try:
            self._watch_task = asyncio.create_task(self._watch_loop(deps))
            logger.info("IPC watcher started (watchfiles + fallback poll)")
        except Exception as err:
            logger.warning("watchfiles not available, using poll-only mode", error=str(err))

        # Fallback poll at slower interval
        self._poll_task = asyncio.create_task(self._fallback_poll_loop(deps))

    def stop(self) -> None:
        self._running = False
        if self._watch_task:
            self._watch_task.cancel()
            self._watch_task = None
        if self._poll_task:
            self._poll_task.cancel()
            self._poll_task = None

    async def dispatch_task(self, data: dict[str, Any], source_group: str, is_main: bool, deps: IpcDeps) -> None:
        """Dispatch a task IPC command directly (used by tests)."""
        await self._dispatcher.dispatch(data, source_group, is_main, deps)

    async def _watch_loop(self, deps: IpcDeps) -> None:
        """Use watchfiles to watch for IPC file changes."""
        try:
            from watchfiles import awatch
            async for _changes in awatch(str(self._ipc_base_dir)):
                if not self._running:
                    break
                await self._process_ipc_files(deps)
        except ImportError:
            logger.debug("watchfiles not installed, using poll only")
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("watchfiles error")

    async def _fallback_poll_loop(self, deps: IpcDeps) -> None:
        """Slow fallback poll."""
        while self._running:
            try:
                await self._process_ipc_files(deps)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Error in IPC fallback poll")
            await asyncio.sleep(FALLBACK_POLL_INTERVAL)

    async def _process_ipc_files(self, deps: IpcDeps) -> None:
        if self._processing:
            return
        self._processing = True

        try:
            if not self._ipc_base_dir.exists():
                return

            group_folders = [
                e.name
                for e in self._ipc_base_dir.iterdir()
                if e.is_dir() and e.name != "errors"
            ]

            registered_groups = deps.registered_groups()

            for source_group in group_folders:
                is_main = source_group == MAIN_GROUP_FOLDER
                messages_dir = self._ipc_base_dir / source_group / "messages"
                tasks_dir = self._ipc_base_dir / source_group / "tasks"

                await self._process_messages_dir(messages_dir, source_group, is_main, registered_groups, deps)
                await self._process_tasks_dir(tasks_dir, source_group, is_main, deps)
        except Exception:
            logger.exception("Error in IPC processing")
        finally:
            self._processing = False

    async def _process_messages_dir(
        self,
        messages_dir: Path,
        source_group: str,
        is_main: bool,
        registered_groups: dict[str, RegisteredGroup],
        deps: IpcDeps,
    ) -> None:
        if not messages_dir.exists():
            return

        message_files = sorted(f for f in messages_dir.iterdir() if f.suffix == ".json")

        for file_path in message_files:
            try:
                data = json.loads(file_path.read_text())

                if data.get("type") == "message" and data.get("chatJid") and data.get("text"):
                    target_group = registered_groups.get(data["chatJid"])
                    auth = AuthorizationPolicy(AuthContext(source_group=source_group, is_main=is_main))
                    if auth.can_send_message(target_group.folder if target_group else ""):
                        await deps.send_message(data["chatJid"], data["text"])
                        logger.info("IPC message sent", chat_jid=data["chatJid"], source_group=source_group)
                    else:
                        logger.warning("Unauthorized IPC message attempt blocked", chat_jid=data["chatJid"], source_group=source_group)

                elif data.get("type") == "media" and data.get("chatJid") and data.get("filePath") and data.get("mediaType"):
                    if not deps.send_media:
                        logger.warning("sendMedia not available, ignoring media IPC", source_group=source_group)
                    else:
                        target_group = registered_groups.get(data["chatJid"])
                        auth = AuthorizationPolicy(AuthContext(source_group=source_group, is_main=is_main))
                        if auth.can_send_message(target_group.folder if target_group else ""):
                            group_dir = GroupPaths.group_dir(source_group)
                            resolved = (group_dir / data["filePath"]).resolve()
                            # Path traversal check
                            if not str(resolved).startswith(str(group_dir)):
                                logger.warning("Media path traversal attempt blocked", source_group=source_group)
                            else:
                                await deps.send_media(
                                    data["chatJid"], str(resolved), data["mediaType"],
                                    data.get("caption"), data.get("mimetype"),
                                )
                                logger.info("IPC media sent", chat_jid=data["chatJid"], source_group=source_group)
                        else:
                            logger.warning("Unauthorized IPC media attempt blocked", source_group=source_group)

                file_path.unlink()
            except Exception:
                logger.exception("Error processing IPC message", file=file_path.name, source_group=source_group)
                error_dir = self._ipc_base_dir / "errors"
                error_dir.mkdir(parents=True, exist_ok=True)
                try:
                    file_path.rename(error_dir / f"{source_group}-{file_path.name}")
                except Exception:
                    pass

    async def _process_tasks_dir(
        self, tasks_dir: Path, source_group: str, is_main: bool, deps: IpcDeps
    ) -> None:
        if not tasks_dir.exists():
            return

        task_files = sorted(f for f in tasks_dir.iterdir() if f.suffix == ".json")

        for file_path in task_files:
            try:
                data = json.loads(file_path.read_text())
                await self._dispatcher.dispatch(data, source_group, is_main, deps)
                file_path.unlink()
            except Exception:
                logger.exception("Error processing IPC task", file=file_path.name, source_group=source_group)
                error_dir = self._ipc_base_dir / "errors"
                error_dir.mkdir(parents=True, exist_ok=True)
                try:
                    file_path.rename(error_dir / f"{source_group}-{file_path.name}")
                except Exception:
                    pass
