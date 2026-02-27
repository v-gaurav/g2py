"""WhatsApp channel using neonize (Python bindings for whatsmeow)."""

from __future__ import annotations

import asyncio
import hashlib
import os
import time
from pathlib import Path
from typing import Callable, Awaitable

from g2.groups.types import RegisteredGroup
from g2.infrastructure.config import (
    ASSISTANT_HAS_OWN_NUMBER,
    ASSISTANT_NAME,
    GROUPS_DIR,
    STORE_DIR,
)
from g2.infrastructure.logger import logger
from g2.messaging.repository import MessageRepository
from g2.messaging.types import NewMessage, OnChatMetadata, OnInboundMessage
from g2.messaging.whatsapp.metadata_sync import WhatsAppMetadataSync
from g2.messaging.whatsapp.outgoing_queue import OutgoingMessageQueue

GROUP_SYNC_INTERVAL_MS = 24 * 60 * 60 * 1000  # 24 hours

MIME_TO_EXT: dict[str, str] = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/gif": "gif",
    "video/mp4": "mp4",
    "audio/ogg; codecs=opus": "ogg",
    "audio/mpeg": "mp3",
    "audio/mp4": "m4a",
    "application/pdf": "pdf",
}


class WhatsAppChannel:
    """WhatsApp channel using neonize.

    NOTE: neonize integration is stubbed. The actual neonize API calls
    need to be implemented when neonize is installed and tested.
    The structure mirrors the TS Baileys implementation exactly.
    """

    name = "whatsapp"

    def __init__(
        self,
        on_message: OnInboundMessage,
        on_chat_metadata: OnChatMetadata,
        registered_groups: Callable[[], dict[str, RegisteredGroup]],
        chat_repo: MessageRepository | None = None,
    ) -> None:
        self._on_message = on_message
        self._on_chat_metadata = on_chat_metadata
        self._registered_groups = registered_groups
        self._chat_repo = chat_repo
        self._connected = False
        self._message_queue = OutgoingMessageQueue()
        self._metadata_sync: WhatsAppMetadataSync | None = None
        self._reconnect_attempt = 0
        self._client: object | None = None  # neonize client

    async def connect(self) -> None:
        """Connect to WhatsApp via neonize."""
        auth_dir = STORE_DIR / "auth"
        auth_dir.mkdir(parents=True, exist_ok=True)

        try:
            from neonize.client import NewClient
            from neonize.events import (
                ConnectedEv,
                MessageEv,
                PairStatusEv,
            )
            from neonize.utils import log as neonize_log

            db_path = str(auth_dir / "neonize.db")
            self._client = NewClient(db_path)

            # Capture the asyncio loop so neonize callbacks (from Go threads)
            # can schedule coroutines back onto it.
            loop = asyncio.get_event_loop()

            # Register event handlers
            @self._client.event(ConnectedEv)
            def on_connected(_client, _event):
                self._connected = True
                self._reconnect_attempt = 0
                logger.info("Connected to WhatsApp")

                # Flush queued messages
                asyncio.run_coroutine_threadsafe(self._flush_outgoing_queue(), loop)

                # Initialize metadata sync
                if not self._metadata_sync and self._chat_repo:
                    self._metadata_sync = WhatsAppMetadataSync(GROUP_SYNC_INTERVAL_MS, self._chat_repo)

            @self._client.event(MessageEv)
            def on_message(_client, event):
                asyncio.run_coroutine_threadsafe(self._handle_message(event), loop)

            @self._client.event(PairStatusEv)
            def on_pair_status(_client, event):
                logger.info("WhatsApp pairing status", status=str(event))

            # Connect (blocking in neonize, runs forever in background thread)
            loop = asyncio.get_event_loop()
            self._connect_future = loop.run_in_executor(None, self._client.connect)
            self._connect_future.add_done_callback(self._on_connect_done)

        except ImportError:
            logger.error(
                "neonize not installed. Install with: pip install neonize. "
                "Falling back to stub mode — no WhatsApp connection."
            )
            # Stub mode: mark as connected for testing
            self._connected = True

    def _on_connect_done(self, future: asyncio.Future) -> None:
        """Handle unexpected return or exception from neonize connect."""
        try:
            future.result()
        except Exception:
            logger.exception("WhatsApp connection terminated")
        self._connected = False

    async def _handle_message(self, event: object) -> None:
        """Handle incoming WhatsApp message from neonize."""
        try:
            # Extract message data from neonize event
            # The exact API depends on neonize version
            msg = event  # type: ignore
            chat_jid = str(getattr(msg, "Info", {}).get("MessageSource", {}).get("Chat", ""))
            if not chat_jid or chat_jid == "status@broadcast":
                return

            raw_ts = getattr(msg, "Info", {}).get("Timestamp", 0)
            timestamp = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(raw_ts)) if raw_ts else time.strftime(
                "%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()
            )

            is_group = chat_jid.endswith("@g.us")
            self._on_chat_metadata(chat_jid, timestamp, None, "whatsapp", is_group)

            groups = self._registered_groups()
            if chat_jid in groups:
                content = str(getattr(msg, "Message", {}).get("Conversation", "") or
                              getattr(msg, "Message", {}).get("ExtendedTextMessage", {}).get("Text", ""))
                sender = str(getattr(msg, "Info", {}).get("MessageSource", {}).get("Sender", ""))
                sender_name = str(getattr(msg, "Info", {}).get("PushName", sender.split("@")[0]))
                from_me = bool(getattr(msg, "Info", {}).get("MessageSource", {}).get("IsFromMe", False))

                is_bot = (
                    from_me
                    if ASSISTANT_HAS_OWN_NUMBER
                    else content.startswith(f"{ASSISTANT_NAME}:")
                )

                self._on_message(
                    chat_jid,
                    NewMessage(
                        id=str(getattr(msg, "Info", {}).get("ID", "")),
                        chat_jid=chat_jid,
                        sender=sender,
                        sender_name=sender_name,
                        content=content,
                        timestamp=timestamp,
                        is_from_me=from_me,
                        is_bot_message=is_bot,
                    ),
                )
        except Exception:
            logger.exception("Error handling WhatsApp message")

    async def send_message(self, jid: str, text: str) -> None:
        prefixed = text if ASSISTANT_HAS_OWN_NUMBER else f"{ASSISTANT_NAME}: {text}"

        if not self._connected:
            self._message_queue.enqueue(jid, prefixed)
            logger.info("WA disconnected, message queued", jid=jid, queue_size=self._message_queue.size)
            return

        try:
            if self._client and hasattr(self._client, "send_message"):
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, self._client.send_message, jid, prefixed)
            logger.info("Message sent", jid=jid, length=len(prefixed))
        except Exception:
            self._message_queue.enqueue(jid, prefixed)
            logger.warning("Failed to send, message queued", jid=jid, queue_size=self._message_queue.size)

    async def send_media(
        self, jid: str, file_path: str, media_type: str, caption: str | None = None, mimetype: str | None = None
    ) -> None:
        if not self._connected:
            logger.warning("WA disconnected, cannot send media", jid=jid, media_type=media_type)
            return
        # TODO: implement media sending via neonize
        logger.warning("Media sending not yet implemented for neonize", jid=jid, media_type=media_type)

    def is_connected(self) -> bool:
        return self._connected

    def owns_jid(self, jid: str) -> bool:
        return jid.endswith("@g.us") or jid.endswith("@s.whatsapp.net")

    async def disconnect(self) -> None:
        self._connected = False
        if self._client and hasattr(self._client, "disconnect"):
            try:
                self._client.disconnect()
            except Exception:
                pass

    async def set_typing(self, jid: str, is_typing: bool) -> None:
        try:
            if self._client and hasattr(self._client, "send_chat_presence"):
                status = "composing" if is_typing else "paused"
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, self._client.send_chat_presence, jid, status)
        except Exception:
            logger.debug("Failed to update typing status", jid=jid)

    async def sync_metadata(self, force: bool = False) -> None:
        if not self._metadata_sync and self._chat_repo:
            self._metadata_sync = WhatsAppMetadataSync(GROUP_SYNC_INTERVAL_MS, self._chat_repo)
        if self._metadata_sync:

            async def fetch_groups() -> dict:
                if self._client and hasattr(self._client, "get_joined_groups"):
                    loop = asyncio.get_event_loop()
                    return await loop.run_in_executor(None, self._client.get_joined_groups)
                return {}

            await self._metadata_sync.sync(fetch_groups, force)

    async def _flush_outgoing_queue(self) -> None:
        if self._message_queue.size > 0:
            logger.info("Flushing outgoing message queue", count=self._message_queue.size)

        async def sender(jid: str, text: str) -> None:
            if self._client and hasattr(self._client, "send_message"):
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, self._client.send_message, jid, text)
            logger.info("Queued message sent", jid=jid, length=len(text))

        await self._message_queue.flush(sender)
