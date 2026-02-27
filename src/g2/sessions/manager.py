"""Session manager with in-memory cache and archive lifecycle."""

from __future__ import annotations

import json
from datetime import datetime

from g2.groups.paths import GroupPaths
from g2.infrastructure.logger import logger
from g2.sessions.repository import SessionRepository
from g2.sessions.types import ArchivedSession


# --- Transcript parsing ---


def _parse_transcript(content: str) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    for line in content.splitlines():
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
            if entry.get("type") == "user" and entry.get("message", {}).get("content"):
                raw_content = entry["message"]["content"]
                if isinstance(raw_content, str):
                    text = raw_content
                else:
                    text = "".join(c.get("text", "") for c in raw_content)
                if text:
                    messages.append({"role": "user", "content": text})
            elif entry.get("type") == "assistant" and entry.get("message", {}).get("content"):
                parts = entry["message"]["content"]
                text = "".join(c.get("text", "") for c in parts if c.get("type") == "text")
                if text:
                    messages.append({"role": "assistant", "content": text})
        except (json.JSONDecodeError, TypeError, KeyError):
            continue
    return messages


def _format_transcript_markdown(messages: list[dict[str, str]], title: str) -> str:
    now = datetime.now()
    formatted_time = now.strftime("%b %d, %I:%M %p")

    lines = [f"# {title}", "", f"Archived: {formatted_time}", "", "---", ""]
    for msg in messages:
        sender = "User" if msg["role"] == "user" else "G2"
        content = msg["content"][:2000] + "..." if len(msg["content"]) > 2000 else msg["content"]
        lines.append(f"**{sender}**: {content}")
        lines.append("")
    return "\n".join(lines)


def read_and_format_transcript(group_folder: str, session_id: str, name: str) -> str | None:
    """Read a session's .jsonl transcript and format it as markdown."""
    transcript_path = GroupPaths.session_transcript(group_folder, session_id)

    if not transcript_path.exists():
        logger.debug("No transcript found", group_folder=group_folder, session_id=session_id)
        return None

    try:
        content = transcript_path.read_text()
        messages = _parse_transcript(content)
        if not messages:
            logger.debug("No messages to archive", group_folder=group_folder)
            return None
        return _format_transcript_markdown(messages, name)
    except Exception as err:
        logger.warning("Failed to read/format conversation transcript", group_folder=group_folder, error=str(err))
        return None


class SessionManager:
    """Session lifecycle manager with in-memory cache."""

    def __init__(self, session_repo: SessionRepository) -> None:
        self._session_repo = session_repo
        self._sessions: dict[str, str] = {}

    def load_from_db(self) -> None:
        """Load all sessions from DB into memory cache."""
        self._sessions = self._session_repo.get_all_sessions()

    def get(self, group_folder: str) -> str | None:
        return self._sessions.get(group_folder)

    def set(self, group_folder: str, session_id: str) -> None:
        self._sessions[group_folder] = session_id
        self._session_repo.set_session(group_folder, session_id)

    def delete(self, group_folder: str) -> None:
        self._sessions.pop(group_folder, None)
        self._session_repo.delete_session(group_folder)

    def get_all(self) -> dict[str, str]:
        return dict(self._sessions)

    # --- Archive lifecycle ---

    def archive(self, group_folder: str, session_id: str, name: str, content: str) -> None:
        self._session_repo.insert_archive(group_folder, session_id, name, content, datetime.now().isoformat())

    def get_archives(self, group_folder: str) -> list[dict]:
        return self._session_repo.get_archives(group_folder)

    def get_archive_by_id(self, id: int) -> ArchivedSession | None:
        return self._session_repo.get_archive_by_id(id)

    def search(self, group_folder: str, query: str) -> list[dict]:
        return self._session_repo.search_archives(group_folder, query)

    def delete_archive(self, id: int) -> None:
        self._session_repo.delete_archive(id)

    def clear(self, group_folder: str, save_name: str | None = None) -> None:
        """Clear the current session, optionally archiving it first."""
        session_id = self.get(group_folder)
        if session_id and save_name:
            content = read_and_format_transcript(group_folder, session_id, save_name)
            self._session_repo.insert_archive(
                group_folder, session_id, save_name, content or "", datetime.now().isoformat()
            )
        self.delete(group_folder)

    def resume(self, group_folder: str, archive_id: int, save_name: str | None = None) -> str:
        """Resume a previously archived session."""
        target = self._session_repo.get_archive_by_id(archive_id)
        if not target:
            raise ValueError(f"Conversation archive entry not found: {archive_id}")

        if save_name:
            current_session_id = self.get(group_folder)
            if current_session_id:
                content = read_and_format_transcript(group_folder, current_session_id, save_name)
                self._session_repo.insert_archive(
                    group_folder, current_session_id, save_name, content or "", datetime.now().isoformat()
                )

        self.set(group_folder, target.session_id)
        self._session_repo.delete_archive(target.id)
        return target.session_id
