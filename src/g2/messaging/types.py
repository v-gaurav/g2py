"""Messaging domain types and Channel protocol."""

from __future__ import annotations

from typing import Protocol, Callable, Literal, runtime_checkable

from pydantic import BaseModel

from g2.groups.types import RegisteredGroup


class NewMessage(BaseModel):
    id: str
    chat_jid: str
    sender: str
    sender_name: str
    content: str
    timestamp: str
    is_from_me: bool = False
    is_bot_message: bool = False
    media_type: Literal["image", "video", "audio", "document"] | None = None
    media_mimetype: str | None = None
    media_path: str | None = None


@runtime_checkable
class Channel(Protocol):
    name: str

    async def connect(self) -> None: ...
    async def send_message(self, jid: str, text: str) -> None: ...
    def is_connected(self) -> bool: ...
    def owns_jid(self, jid: str) -> bool: ...
    async def disconnect(self) -> None: ...
    async def set_typing(self, jid: str, is_typing: bool) -> None: ...
    async def sync_metadata(self, force: bool = False) -> None: ...
    async def send_media(
        self, jid: str, file_path: str, media_type: str, caption: str | None = None, mimetype: str | None = None
    ) -> None: ...


# Callback types
OnInboundMessage = Callable[[str, NewMessage], None]
OnChatMetadata = Callable[[str, str, str | None, str | None, bool | None], None]
