"""Shared async polling loop abstraction."""

from __future__ import annotations

import asyncio
from typing import Callable, Awaitable

from g2.infrastructure.logger import logger


class PollLoop:
    """An async polling loop that calls a function at regular intervals."""

    def __init__(self, name: str, interval_s: float, fn: Callable[[], Awaitable[None]]) -> None:
        self._name = name
        self._interval = interval_s
        self._fn = fn
        self._task: asyncio.Task[None] | None = None
        self._stopped = False

    def start(self) -> None:
        """Start the polling loop as a background task."""
        self._stopped = False
        self._task = asyncio.create_task(self._loop())
        logger.info(f"{self._name} loop started", interval_s=self._interval)

    def stop(self) -> None:
        """Stop the polling loop."""
        self._stopped = True
        if self._task:
            self._task.cancel()
            self._task = None

    async def _loop(self) -> None:
        while not self._stopped:
            try:
                await self._fn()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception(f"Error in {self._name} loop")
            if not self._stopped:
                await asyncio.sleep(self._interval)


def start_poll_loop(name: str, interval_s: float, fn: Callable[[], Awaitable[None]]) -> PollLoop:
    """Create and start a polling loop. Returns a handle to stop it."""
    loop = PollLoop(name, interval_s, fn)
    loop.start()
    return loop
