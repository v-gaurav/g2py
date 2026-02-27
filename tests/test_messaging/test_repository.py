"""Tests for message repository."""

import pytest

from g2.infrastructure.database import AppDatabase
from g2.messaging.types import NewMessage


@pytest.fixture
def msg_repo():
    db = AppDatabase()
    db._init_test()
    return db.message_repo


def _msg(id: str = "m1", chat_jid: str = "group@g.us", content: str = "Hello", timestamp: str = "2024-01-01T00:00:01") -> NewMessage:
    return NewMessage(
        id=id,
        chat_jid=chat_jid,
        sender="alice@s.whatsapp.net",
        sender_name="Alice",
        content=content,
        timestamp=timestamp,
    )


class TestStoreMessage:
    def test_store_and_retrieve(self, msg_repo):
        msg_repo.store_message(_msg())
        messages, _ = msg_repo.get_new_messages(["group@g.us"], "", "G2")
        assert len(messages) == 1
        assert messages[0].content == "Hello"

    def test_duplicate_ignored(self, msg_repo):
        msg_repo.store_message(_msg())
        msg_repo.store_message(_msg())
        messages, _ = msg_repo.get_new_messages(["group@g.us"], "", "G2")
        assert len(messages) == 1


class TestGetNewMessages:
    def test_filters_by_timestamp(self, msg_repo):
        msg_repo.store_message(_msg(id="m1", timestamp="2024-01-01T00:00:01"))
        msg_repo.store_message(_msg(id="m2", timestamp="2024-01-01T00:00:03"))

        messages, new_ts = msg_repo.get_new_messages(["group@g.us"], "2024-01-01T00:00:02", "G2")
        assert len(messages) == 1
        assert messages[0].id == "m2"
        assert new_ts == "2024-01-01T00:00:03"

    def test_filters_by_jids(self, msg_repo):
        msg_repo.store_message(_msg(id="m1", chat_jid="group1@g.us"))
        msg_repo.store_message(_msg(id="m2", chat_jid="group2@g.us"))

        messages, _ = msg_repo.get_new_messages(["group1@g.us"], "", "G2")
        assert len(messages) == 1
        assert messages[0].chat_jid == "group1@g.us"

    def test_excludes_bot_messages(self, msg_repo):
        msg_repo.store_message(_msg(id="m1"))
        msg_repo.store_message(NewMessage(
            id="m2", chat_jid="group@g.us", sender="bot", sender_name="Bot",
            content="Bot message", timestamp="2024-01-01T00:00:02", is_bot_message=True,
        ))

        messages, _ = msg_repo.get_new_messages(["group@g.us"], "", "G2")
        assert len(messages) == 1
        assert messages[0].id == "m1"

    def test_empty_jids(self, msg_repo):
        messages, ts = msg_repo.get_new_messages([], "", "G2")
        assert messages == []

    def test_no_messages(self, msg_repo):
        messages, ts = msg_repo.get_new_messages(["group@g.us"], "", "G2")
        assert messages == []
        assert ts == ""


class TestGetMessagesSince:
    def test_returns_messages_after_timestamp(self, msg_repo):
        msg_repo.store_message(_msg(id="m1", timestamp="2024-01-01T00:00:01"))
        msg_repo.store_message(_msg(id="m2", timestamp="2024-01-01T00:00:03"))

        messages = msg_repo.get_messages_since("group@g.us", "2024-01-01T00:00:02", "G2")
        assert len(messages) == 1
        assert messages[0].id == "m2"


class TestChatMetadata:
    def test_upsert_new_chat(self, msg_repo):
        msg_repo.upsert_chat("group@g.us", "2024-01-01T00:00:00", "Test Group", "whatsapp", True)
        chats = msg_repo.get_all_chats()
        assert len(chats) == 1
        assert chats[0]["name"] == "Test Group"
        assert chats[0]["is_group"] == 1

    def test_upsert_existing_chat(self, msg_repo):
        msg_repo.upsert_chat("group@g.us", "2024-01-01T00:00:00", "Old Name")
        msg_repo.upsert_chat("group@g.us", "2024-01-01T00:00:01", "New Name")
        chats = msg_repo.get_all_chats()
        assert len(chats) == 1
        assert chats[0]["name"] == "New Name"

    def test_update_chat_name(self, msg_repo):
        msg_repo.upsert_chat("group@g.us", "2024-01-01T00:00:00", "Old Name")
        msg_repo.update_chat_name("group@g.us", "Updated")
        chats = msg_repo.get_all_chats()
        assert chats[0]["name"] == "Updated"
