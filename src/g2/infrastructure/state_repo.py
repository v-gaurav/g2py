"""Router state key-value persistence."""

from __future__ import annotations

import sqlite3


class StateRepository:
    def __init__(self, db: sqlite3.Connection) -> None:
        self._db = db

    def get_router_state(self, key: str) -> str | None:
        row = self._db.execute("SELECT value FROM router_state WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    def set_router_state(self, key: str, value: str) -> None:
        self._db.execute("INSERT OR REPLACE INTO router_state (key, value) VALUES (?, ?)", (key, value))
        self._db.commit()
