"""IPC command dispatcher and base handler."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, TYPE_CHECKING

from g2.infrastructure.logger import logger

if TYPE_CHECKING:
    from g2.ipc.watcher import IpcDeps


class IpcHandlerError(Exception):
    """Error raised by IPC handlers for expected failures."""

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.details = details or {}


@dataclass
class HandlerContext:
    source_group: str
    is_main: bool
    deps: IpcDeps


class IpcCommandHandler(ABC):
    """Base class for IPC command handlers."""

    @property
    @abstractmethod
    def command(self) -> str: ...

    @abstractmethod
    async def validate(self, data: dict[str, Any]) -> Any: ...

    @abstractmethod
    async def execute(self, payload: Any, context: HandlerContext) -> None: ...

    async def handle(self, data: dict[str, Any], source_group: str, is_main: bool, deps: IpcDeps) -> None:
        context = HandlerContext(source_group=source_group, is_main=is_main, deps=deps)
        validated = await self.validate(data)
        await self.execute(validated, context)


class IpcCommandDispatcher:
    """Routes IPC commands to registered handlers."""

    def __init__(self, handlers: list[IpcCommandHandler]) -> None:
        self._handlers: dict[str, IpcCommandHandler] = {h.command: h for h in handlers}

    async def dispatch(self, data: dict[str, Any], source_group: str, is_main: bool, deps: IpcDeps) -> None:
        command_type = data.get("type")
        handler = self._handlers.get(command_type)  # type: ignore[arg-type]
        if not handler:
            logger.warning("Unknown IPC task type", type=command_type)
            return
        try:
            await handler.handle(data, source_group, is_main, deps)
        except IpcHandlerError as err:
            logger.warning(err.args[0], command=command_type, source_group=source_group, **err.details)
        except Exception:
            raise
