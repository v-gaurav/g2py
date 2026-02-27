"""WhatsApp group metadata syncing."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Callable, Awaitable

from g2.infrastructure.logger import logger
from g2.messaging.repository import MessageRepository


class WhatsAppMetadataSync:
    """Syncs WhatsApp group metadata (names) periodically."""

    def __init__(self, interval_ms: int, chat_repo: MessageRepository) -> None:
        self._interval_ms = interval_ms
        self._chat_repo = chat_repo
        self._timer_started = False
        self._periodic_task: asyncio.Task | None = None

    async def sync(
        self,
        fetch_groups: Callable[[], Awaitable[dict[str, dict]]],
        force: bool = False,
    ) -> None:
        if not force:
            last_sync = self._chat_repo.get_last_group_sync()
            if last_sync:
                try:
                    last_sync_time = datetime.fromisoformat(last_sync)
                    elapsed = (datetime.now() - last_sync_time).total_seconds() * 1000
                    if elapsed < self._interval_ms:
                        logger.debug("Skipping group sync - synced recently", last_sync=last_sync)
                        return
                except (ValueError, TypeError):
                    pass  # Bad timestamp, proceed with sync

        try:
            logger.info("Syncing group metadata from WhatsApp...")
            groups = await fetch_groups()

            count = 0
            for jid, metadata in groups.items():
                subject = metadata.get("subject")
                if subject:
                    self._chat_repo.update_chat_name(jid, subject)
                    count += 1

            self._chat_repo.set_last_group_sync()
            logger.info("Group metadata synced", count=count)
        except Exception:
            logger.exception("Failed to sync group metadata")

    def start_periodic_sync(
        self,
        fetch_groups: Callable[[], Awaitable[dict[str, dict]]],
    ) -> None:
        """Start periodic sync. Only starts the timer once (idempotent)."""
        if self._timer_started:
            return
        self._timer_started = True

        async def periodic() -> None:
            while True:
                await asyncio.sleep(self._interval_ms / 1000)
                try:
                    await self.sync(fetch_groups)
                except Exception:
                    logger.exception("Periodic group sync failed")

        self._periodic_task = asyncio.create_task(periodic())
