"""Tests for session manager."""

import pytest

from g2.infrastructure.database import AppDatabase
from g2.sessions.manager import SessionManager, _parse_transcript, _format_transcript_markdown


@pytest.fixture
def session_manager():
    db = AppDatabase()
    db._init_test()
    return SessionManager(db.session_repo)


class TestSessionManager:
    def test_set_and_get(self, session_manager):
        session_manager.set("main", "sess-123")
        assert session_manager.get("main") == "sess-123"

    def test_get_nonexistent(self, session_manager):
        assert session_manager.get("nonexistent") is None

    def test_delete(self, session_manager):
        session_manager.set("main", "sess-123")
        session_manager.delete("main")
        assert session_manager.get("main") is None

    def test_get_all(self, session_manager):
        session_manager.set("main", "sess-1")
        session_manager.set("other", "sess-2")
        all_sessions = session_manager.get_all()
        assert len(all_sessions) == 2
        assert all_sessions["main"] == "sess-1"

    def test_load_from_db(self):
        db = AppDatabase()
        db._init_test()
        db.session_repo.set_session("main", "sess-db")

        sm = SessionManager(db.session_repo)
        sm.load_from_db()
        assert sm.get("main") == "sess-db"


class TestArchiveLifecycle:
    def test_archive_and_retrieve(self, session_manager):
        session_manager.archive("main", "sess-1", "My Archive", "Some content")
        archives = session_manager.get_archives("main")
        assert len(archives) == 1
        assert archives[0]["name"] == "My Archive"

    def test_search(self, session_manager):
        session_manager.archive("main", "sess-1", "Archive 1", "keyword abc")
        session_manager.archive("main", "sess-2", "Archive 2", "other content")
        results = session_manager.search("main", "keyword")
        assert len(results) == 1
        assert results[0]["name"] == "Archive 1"

    def test_clear_without_save(self, session_manager):
        session_manager.set("main", "sess-1")
        session_manager.clear("main")
        assert session_manager.get("main") is None

    def test_resume_restores_session(self, session_manager):
        session_manager.archive("main", "sess-old", "Old Session", "content")
        archives = session_manager.get_archives("main")
        archive_id = archives[0]["id"]

        session_manager.set("main", "sess-current")
        restored = session_manager.resume("main", archive_id)
        assert restored == "sess-old"
        assert session_manager.get("main") == "sess-old"

    def test_resume_nonexistent_raises(self, session_manager):
        with pytest.raises(ValueError, match="not found"):
            session_manager.resume("main", 999)


class TestTranscriptParsing:
    def test_parses_user_message(self):
        line = '{"type": "user", "message": {"content": "Hello"}}'
        messages = _parse_transcript(line)
        assert len(messages) == 1
        assert messages[0]["role"] == "user"
        assert messages[0]["content"] == "Hello"

    def test_parses_assistant_message(self):
        line = '{"type": "assistant", "message": {"content": [{"type": "text", "text": "Hi"}]}}'
        messages = _parse_transcript(line)
        assert len(messages) == 1
        assert messages[0]["role"] == "assistant"
        assert messages[0]["content"] == "Hi"

    def test_ignores_invalid_json(self):
        messages = _parse_transcript("not json\n{invalid}")
        assert len(messages) == 0

    def test_ignores_empty_lines(self):
        messages = _parse_transcript("\n\n\n")
        assert len(messages) == 0


class TestFormatTranscriptMarkdown:
    def test_formats_messages(self):
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
        ]
        result = _format_transcript_markdown(messages, "Test Session")
        assert "# Test Session" in result
        assert "**User**: Hello" in result
        assert "**G2**: Hi there" in result

    def test_truncates_long_content(self):
        messages = [{"role": "user", "content": "x" * 3000}]
        result = _format_transcript_markdown(messages, "Test")
        assert "..." in result
