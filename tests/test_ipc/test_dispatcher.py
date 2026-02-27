"""Tests for IPC dispatcher."""

import pytest

from g2.ipc.dispatcher import IpcCommandDispatcher, IpcCommandHandler, IpcHandlerError, HandlerContext
from typing import Any


class MockHandler(IpcCommandHandler):
    def __init__(self, cmd: str):
        self._command = cmd
        self.called_with = None

    @property
    def command(self) -> str:
        return self._command

    async def validate(self, data: dict[str, Any]) -> Any:
        return data

    async def execute(self, payload: Any, context: HandlerContext) -> None:
        self.called_with = (payload, context)


class ErrorHandler(IpcCommandHandler):
    @property
    def command(self) -> str:
        return "error_cmd"

    async def validate(self, data: dict[str, Any]) -> Any:
        return data

    async def execute(self, payload: Any, context: HandlerContext) -> None:
        raise IpcHandlerError("Test error", {"detail": "test"})


class TestIpcDispatcher:
    @pytest.mark.asyncio
    async def test_dispatches_to_correct_handler(self):
        handler_a = MockHandler("cmd_a")
        handler_b = MockHandler("cmd_b")
        dispatcher = IpcCommandDispatcher([handler_a, handler_b])

        await dispatcher.dispatch({"type": "cmd_a", "data": "test"}, "main", True, None)
        assert handler_a.called_with is not None
        assert handler_b.called_with is None

    @pytest.mark.asyncio
    async def test_unknown_command_ignored(self):
        dispatcher = IpcCommandDispatcher([MockHandler("known")])
        # Should not raise
        await dispatcher.dispatch({"type": "unknown"}, "main", True, None)

    @pytest.mark.asyncio
    async def test_handler_error_caught(self):
        dispatcher = IpcCommandDispatcher([ErrorHandler()])
        # Should not raise — IpcHandlerError is caught
        await dispatcher.dispatch({"type": "error_cmd"}, "main", True, None)

    @pytest.mark.asyncio
    async def test_handler_context(self):
        handler = MockHandler("test")
        dispatcher = IpcCommandDispatcher([handler])

        await dispatcher.dispatch({"type": "test"}, "project-a", False, None)
        assert handler.called_with is not None
        _, context = handler.called_with
        assert context.source_group == "project-a"
        assert context.is_main is False
