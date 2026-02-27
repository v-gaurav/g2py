"""Registry pattern for multiple channels."""

from __future__ import annotations

from g2.infrastructure.logger import logger
from g2.messaging.types import Channel


class ChannelRegistry:
    """Manages registered channels and routes JIDs to the correct channel."""

    def __init__(self) -> None:
        self._channels: list[Channel] = []

    def register(self, channel: Channel) -> None:
        if any(c.name == channel.name for c in self._channels):
            raise ValueError(f'Channel "{channel.name}" is already registered')
        self._channels.append(channel)

    def find_by_jid(self, jid: str) -> Channel | None:
        return next((c for c in self._channels if c.owns_jid(jid)), None)

    def find_connected_by_jid(self, jid: str) -> Channel | None:
        return next((c for c in self._channels if c.owns_jid(jid) and c.is_connected()), None)

    def get_all(self) -> list[Channel]:
        return list(self._channels)

    async def sync_all_metadata(self, force: bool = False) -> None:
        for channel in self._channels:
            if hasattr(channel, "sync_metadata"):
                await channel.sync_metadata(force)

    async def disconnect_all(self) -> None:
        for channel in self._channels:
            try:
                await channel.disconnect()
            except Exception:
                logger.exception("Error disconnecting channel", channel=channel.name)
