"""Message and chat metadata DB operations."""

from __future__ import annotations

import sqlite3

from g2.messaging.types import NewMessage


class MessageRepository:
    """Combined message + chat metadata repository."""

    def __init__(self, db: sqlite3.Connection) -> None:
        self._db = db

    # --- Message storage ---

    def store_message(self, msg: NewMessage) -> None:
        self._db.execute(
            """INSERT OR IGNORE INTO messages
               (id, chat_jid, sender, sender_name, content, timestamp, is_from_me, is_bot_message,
                media_type, media_mimetype, media_path)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                msg.id,
                msg.chat_jid,
                msg.sender,
                msg.sender_name,
                msg.content,
                msg.timestamp,
                1 if msg.is_from_me else 0,
                1 if msg.is_bot_message else 0,
                msg.media_type,
                msg.media_mimetype,
                msg.media_path,
            ),
        )
        self._db.commit()

    def get_new_messages(
        self, jids: list[str], since_timestamp: str, assistant_name: str
    ) -> tuple[list[NewMessage], str]:
        """Get messages newer than since_timestamp for the given JIDs.

        Returns (messages, new_timestamp).
        """
        if not jids:
            return [], since_timestamp

        placeholders = ",".join("?" * len(jids))
        params: list[str | int] = list(jids)
        params.append(since_timestamp)
        params.append(0)  # is_bot_message = 0

        rows = self._db.execute(
            f"""SELECT * FROM messages
                WHERE chat_jid IN ({placeholders})
                AND timestamp > ?
                AND is_bot_message = ?
                ORDER BY timestamp""",
            params,
        ).fetchall()

        if not rows:
            return [], since_timestamp

        messages = [self._row_to_message(row) for row in rows]
        new_ts = messages[-1].timestamp
        return messages, new_ts

    def get_messages_since(self, chat_jid: str, since_timestamp: str, assistant_name: str) -> list[NewMessage]:
        """Get all non-bot messages for a chat since a timestamp."""
        rows = self._db.execute(
            """SELECT * FROM messages
               WHERE chat_jid = ? AND timestamp > ? AND is_bot_message = 0
               ORDER BY timestamp""",
            (chat_jid, since_timestamp),
        ).fetchall()
        return [self._row_to_message(row) for row in rows]

    # --- Chat metadata ---

    def upsert_chat(
        self,
        jid: str,
        timestamp: str,
        name: str | None = None,
        channel: str | None = None,
        is_group: bool | None = None,
    ) -> None:
        """Create or update chat metadata."""
        existing = self._db.execute("SELECT * FROM chats WHERE jid = ?", (jid,)).fetchone()

        if existing:
            updates: list[str] = ["last_message_time = ?"]
            values: list[str | int] = [timestamp]
            if name:
                updates.append("name = ?")
                values.append(name)
            if channel:
                updates.append("channel = ?")
                values.append(channel)
            if is_group is not None:
                updates.append("is_group = ?")
                values.append(1 if is_group else 0)
            values.append(jid)
            self._db.execute(f"UPDATE chats SET {', '.join(updates)} WHERE jid = ?", values)
        else:
            self._db.execute(
                "INSERT INTO chats (jid, name, last_message_time, channel, is_group) VALUES (?, ?, ?, ?, ?)",
                (jid, name or "", timestamp, channel or "", 1 if is_group else 0),
            )
        self._db.commit()

    def update_chat_name(self, jid: str, name: str) -> None:
        """Update the name of a chat. Creates the chat if it doesn't exist."""
        existing = self._db.execute("SELECT * FROM chats WHERE jid = ?", (jid,)).fetchone()
        if existing:
            self._db.execute("UPDATE chats SET name = ? WHERE jid = ?", (name, jid))
        else:
            self._db.execute(
                "INSERT INTO chats (jid, name, last_message_time, channel, is_group) VALUES (?, ?, '', '', 0)",
                (jid, name),
            )
        self._db.commit()

    def get_all_chats(self) -> list[dict]:
        rows = self._db.execute("SELECT * FROM chats ORDER BY last_message_time DESC").fetchall()
        return [dict(row) for row in rows]

    def get_last_group_sync(self) -> str | None:
        row = self._db.execute("SELECT value FROM router_state WHERE key = 'last_group_sync'").fetchone()
        return row[0] if row else None

    def set_last_group_sync(self) -> None:
        from datetime import datetime

        self._db.execute(
            "INSERT OR REPLACE INTO router_state (key, value) VALUES ('last_group_sync', ?)",
            (datetime.now().isoformat(),),
        )
        self._db.commit()

    def _row_to_message(self, row: sqlite3.Row) -> NewMessage:
        return NewMessage(
            id=row["id"],
            chat_jid=row["chat_jid"],
            sender=row["sender"],
            sender_name=row["sender_name"],
            content=row["content"],
            timestamp=row["timestamp"],
            is_from_me=bool(row["is_from_me"]),
            is_bot_message=bool(row["is_bot_message"]),
            media_type=row["media_type"] if "media_type" in row.keys() else None,
            media_mimetype=row["media_mimetype"] if "media_mimetype" in row.keys() else None,
            media_path=row["media_path"] if "media_path" in row.keys() else None,
        )
