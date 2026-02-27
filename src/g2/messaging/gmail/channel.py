"""Gmail channel — polls for emails, delivers as messages, sends replies."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import re
from pathlib import Path
from typing import Callable

from g2.groups.types import RegisteredGroup
from g2.infrastructure.logger import logger
from g2.infrastructure.poll_loop import PollLoop, start_poll_loop
from g2.messaging.types import NewMessage, OnChatMetadata, OnInboundMessage

GMAIL_JID = "gmail:inbox"


class GmailMessage:
    def __init__(self, id: str, thread_id: str, from_: str, to: str, subject: str, body: str, date: str) -> None:
        self.id = id
        self.thread_id = thread_id
        self.from_ = from_
        self.to = to
        self.subject = subject
        self.body = body
        self.date = date


class GmailClient:
    """Gmail API client wrapper with OAuth token refresh."""

    def __init__(self, config_dir: str) -> None:
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        keys_path = Path(config_dir) / "gcp-oauth.keys.json"
        creds_path = Path(config_dir) / "credentials.json"

        keys = json.loads(keys_path.read_text())
        creds_data = json.loads(creds_path.read_text())

        installed = keys.get("installed", keys.get("web", {}))
        client_id = installed.get("client_id", "")
        client_secret = installed.get("client_secret", "")

        self._creds = Credentials(
            token=creds_data.get("access_token"),
            refresh_token=creds_data.get("refresh_token"),
            token_uri="https://oauth2.googleapis.com/token",
            client_id=client_id,
            client_secret=client_secret,
        )
        self._creds_path = creds_path

        self._gmail = build("gmail", "v1", credentials=self._creds)

    def _save_creds(self) -> None:
        if self._creds.token:
            existing = json.loads(self._creds_path.read_text())
            existing["access_token"] = self._creds.token
            if self._creds.refresh_token:
                existing["refresh_token"] = self._creds.refresh_token
            self._creds_path.write_text(json.dumps(existing, indent=2))

    async def search(self, query: str, max_results: int = 10) -> list[GmailMessage]:
        loop = asyncio.get_event_loop()

        def _search():
            res = self._gmail.users().messages().list(userId="me", q=query, maxResults=max_results).execute()
            return res.get("messages", [])

        message_ids = await loop.run_in_executor(None, _search)
        messages: list[GmailMessage] = []
        for item in message_ids:
            msg = await self.get_message(item["id"])
            if msg:
                messages.append(msg)
        return messages

    async def get_message(self, id: str) -> GmailMessage | None:
        loop = asyncio.get_event_loop()

        def _get():
            return self._gmail.users().messages().get(userId="me", id=id, format="full").execute()

        msg = await loop.run_in_executor(None, _get)
        if not msg.get("id") or not msg.get("threadId"):
            return None

        headers = msg.get("payload", {}).get("headers", [])

        def get_header(name: str) -> str:
            return next((h["value"] for h in headers if h.get("name", "").lower() == name.lower()), "")

        body = self._extract_body(msg.get("payload"))

        return GmailMessage(
            id=msg["id"],
            thread_id=msg["threadId"],
            from_=get_header("From"),
            to=get_header("To"),
            subject=get_header("Subject"),
            body=body,
            date=get_header("Date"),
        )

    async def send_reply(
        self, thread_id: str, to: str, subject: str, body: str, in_reply_to: str | None = None
    ) -> None:
        reply_subject = subject if subject.startswith("Re:") else f"Re: {subject}"
        parts = [f"To: {to}", f"Subject: {reply_subject}", "Content-Type: text/plain; charset=utf-8"]
        if in_reply_to:
            parts.extend([f"In-Reply-To: {in_reply_to}", f"References: {in_reply_to}"])
        parts.extend(["", body])

        raw = base64.urlsafe_b64encode("\r\n".join(parts).encode()).decode().rstrip("=")

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            lambda: self._gmail.users().messages().send(userId="me", body={"raw": raw, "threadId": thread_id}).execute(),
        )

    async def mark_as_read(self, message_id: str) -> None:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            lambda: self._gmail.users()
            .messages()
            .modify(userId="me", id=message_id, body={"removeLabelIds": ["UNREAD"]})
            .execute(),
        )

    def _extract_body(self, payload: dict | None) -> str:
        if not payload:
            return ""
        if payload.get("mimeType") == "text/plain" and payload.get("body", {}).get("data"):
            return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")
        for part in payload.get("parts", []):
            if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
                return base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="replace")
        for part in payload.get("parts", []):
            text = self._extract_body(part)
            if text:
                return text
        return ""


def _extract_name(from_: str) -> str:
    match = re.match(r'^"?([^"<]+)"?\s*<', from_)
    return match.group(1).strip() if match else from_.split("@")[0]


class GmailChannel:
    """Gmail channel — polls for emails, delivers as inbound messages."""

    name = "gmail"

    def __init__(
        self,
        on_message: OnInboundMessage,
        on_chat_metadata: OnChatMetadata,
        registered_groups: Callable[[], dict[str, RegisteredGroup]],
        trigger_address: str,
        poll_interval_ms: int,
        group_folder: str,
    ) -> None:
        self._on_message = on_message
        self._on_chat_metadata = on_chat_metadata
        self._registered_groups = registered_groups
        self._trigger_address = trigger_address
        self._poll_interval_s = poll_interval_ms / 1000
        self._group_folder = group_folder
        self._client: GmailClient | None = None
        self._connected = False
        self._poll_handle: PollLoop | None = None
        self._processed_ids: set[str] = set()
        self._reply_target: dict | None = None

    async def connect(self) -> None:
        config_dir = str(Path.home() / ".gmail-mcp")
        self._client = GmailClient(config_dir)
        self._connected = True

        await self._seed_processed_ids()
        self._poll_handle = start_poll_loop("Gmail", self._poll_interval_s, self._poll)
        logger.info("Gmail channel connected", trigger_address=self._trigger_address)

    async def send_message(self, _jid: str, text: str) -> None:
        if not self._client:
            logger.warning("Gmail client not initialized")
            return
        if not self._reply_target:
            logger.warning("No reply target set, cannot send Gmail reply")
            return

        try:
            await self._client.send_reply(
                self._reply_target["thread_id"],
                self._reply_target["from"],
                self._reply_target["subject"],
                text,
                self._reply_target["message_id"],
            )
            logger.info("Gmail reply sent", to=self._reply_target["from"])
        except Exception:
            logger.exception("Failed to send Gmail reply")

    async def send_media(
        self, jid: str, file_path: str, media_type: str, caption: str | None = None, mimetype: str | None = None
    ) -> None:
        logger.warning("Gmail media sending not supported")

    def is_connected(self) -> bool:
        return self._connected

    def owns_jid(self, jid: str) -> bool:
        return jid.startswith("gmail:")

    async def disconnect(self) -> None:
        if self._poll_handle:
            self._poll_handle.stop()
            self._poll_handle = None
        self._connected = False
        logger.info("Gmail channel disconnected")

    async def set_typing(self, jid: str, is_typing: bool) -> None:
        pass  # No typing indicators for email

    async def sync_metadata(self, force: bool = False) -> None:
        pass  # No metadata sync for email

    async def _seed_processed_ids(self) -> None:
        if not self._client:
            return
        try:
            query = f"to:{self._trigger_address}"
            recent = await self._client.search(query, 20)
            for msg in recent:
                self._processed_ids.add(msg.id)
            logger.info("Gmail: seeded processed IDs", count=len(self._processed_ids))
        except Exception:
            logger.warning("Gmail: failed to seed processed IDs")

    async def _poll(self) -> None:
        if not self._client:
            return

        query = f"to:{self._trigger_address} is:unread"
        try:
            messages = await self._client.search(query, 5)
        except Exception:
            logger.exception("Gmail poll error")
            return

        from datetime import datetime

        for msg in messages:
            if msg.id in self._processed_ids:
                continue
            self._processed_ids.add(msg.id)

            timestamp = datetime.now().isoformat()
            try:
                from email.utils import parsedate_to_datetime

                timestamp = parsedate_to_datetime(msg.date).isoformat()
            except Exception:
                pass

            self._reply_target = {
                "thread_id": msg.thread_id,
                "from": msg.from_,
                "subject": msg.subject,
                "message_id": msg.id,
            }

            self._on_chat_metadata(GMAIL_JID, timestamp, "Gmail Inbox", "gmail", False)

            content = f"[Email from {msg.from_}]\nSubject: {msg.subject}\n\n{msg.body}"
            self._on_message(
                GMAIL_JID,
                NewMessage(
                    id=msg.id,
                    chat_jid=GMAIL_JID,
                    sender=msg.from_,
                    sender_name=_extract_name(msg.from_),
                    content=content,
                    timestamp=timestamp,
                    is_from_me=False,
                ),
            )

            try:
                await self._client.mark_as_read(msg.id)
            except Exception:
                logger.warning("Failed to mark email as read", id=msg.id)

            logger.info("Gmail: new email processed", from_=msg.from_, subject=msg.subject)
