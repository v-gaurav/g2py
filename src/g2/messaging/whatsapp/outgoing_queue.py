"""Rate-limited outbound message queue."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Awaitable


@dataclass
class QueuedMessage:
    jid: str
    text: str


class OutgoingMessageQueue:
    """Queue for messages that couldn't be sent while disconnected."""

    def __init__(self) -> None:
        self._queue: list[QueuedMessage] = []
        self._flushing = False

    def enqueue(self, jid: str, text: str) -> None:
        self._queue.append(QueuedMessage(jid=jid, text=text))

    @property
    def size(self) -> int:
        return len(self._queue)

    async def flush(self, sender: Callable[[str, str], Awaitable[None]]) -> None:
        if self._flushing or not self._queue:
            return
        self._flushing = True
        try:
            while self._queue:
                item = self._queue[0]
                await sender(item.jid, item.text)
                self._queue.pop(0)
        finally:
            self._flushing = False
