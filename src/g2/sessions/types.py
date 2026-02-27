"""Session domain types."""

from __future__ import annotations

from pydantic import BaseModel


class ArchivedSession(BaseModel):
    id: int
    group_folder: str
    session_id: str
    name: str
    content: str
    archived_at: str
