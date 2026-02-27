"""Session and conversation archive persistence."""

from __future__ import annotations

import sqlite3

from g2.sessions.types import ArchivedSession


class SessionRepository:
    def __init__(self, db: sqlite3.Connection) -> None:
        self._db = db

    # --- Active sessions ---

    def get_session(self, group_folder: str) -> str | None:
        row = self._db.execute("SELECT session_id FROM sessions WHERE group_folder = ?", (group_folder,)).fetchone()
        return row["session_id"] if row else None

    def set_session(self, group_folder: str, session_id: str) -> None:
        self._db.execute(
            "INSERT OR REPLACE INTO sessions (group_folder, session_id) VALUES (?, ?)", (group_folder, session_id)
        )
        self._db.commit()

    def delete_session(self, group_folder: str) -> None:
        self._db.execute("DELETE FROM sessions WHERE group_folder = ?", (group_folder,))
        self._db.commit()

    def get_all_sessions(self) -> dict[str, str]:
        rows = self._db.execute("SELECT group_folder, session_id FROM sessions").fetchall()
        return {row["group_folder"]: row["session_id"] for row in rows}

    # --- Archives ---

    def insert_archive(
        self, group_folder: str, session_id: str, name: str, content: str, archived_at: str
    ) -> None:
        self._db.execute(
            """INSERT INTO conversation_archives (group_folder, session_id, name, content, archived_at)
               VALUES (?, ?, ?, ?, ?)""",
            (group_folder, session_id, name, content, archived_at),
        )
        self._db.commit()

    def get_archives(self, group_folder: str) -> list[dict]:
        rows = self._db.execute(
            """SELECT id, group_folder, session_id, name, archived_at
               FROM conversation_archives WHERE group_folder = ? ORDER BY archived_at DESC""",
            (group_folder,),
        ).fetchall()
        return [dict(row) for row in rows]

    def get_archive_by_id(self, id: int) -> ArchivedSession | None:
        row = self._db.execute("SELECT * FROM conversation_archives WHERE id = ?", (id,)).fetchone()
        if not row:
            return None
        return ArchivedSession(**dict(row))

    def search_archives(self, group_folder: str, query: str) -> list[dict]:
        rows = self._db.execute(
            """SELECT id, group_folder, session_id, name, archived_at
               FROM conversation_archives
               WHERE group_folder = ? AND content LIKE ? ORDER BY archived_at DESC""",
            (group_folder, f"%{query}%"),
        ).fetchall()
        return [dict(row) for row in rows]

    def delete_archive(self, id: int) -> None:
        self._db.execute("DELETE FROM conversation_archives WHERE id = ?", (id,))
        self._db.commit()
