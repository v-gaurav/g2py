"""Resettable idle timer using asyncio."""

from __future__ import annotations

import asyncio
from typing import Callable, Awaitable


class IdleTimer:
    """Calls callback after timeout_s of inactivity (no reset() calls)."""

    def __init__(self, callback: Callable[[], Awaitable[None] | None], timeout_s: float) -> None:
        self._callback = callback
        self._timeout = timeout_s
        self._task: asyncio.Task[None] | None = None

    def reset(self) -> None:
        """Reset the timer. Cancels any pending callback and starts a new countdown."""
        if self._task:
            self._task.cancel()
        self._task = asyncio.create_task(self._fire())

    async def _fire(self) -> None:
        await asyncio.sleep(self._timeout)
        result = self._callback()
        if asyncio.iscoroutine(result):
            await result

    def clear(self) -> None:
        """Cancel the timer without firing the callback."""
        if self._task:
            self._task.cancel()
            self._task = None
