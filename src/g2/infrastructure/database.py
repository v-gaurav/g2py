"""SQLite database schema, migrations, and AppDatabase composition root."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from g2.infrastructure.config import ASSISTANT_NAME, DATA_DIR, STORE_DIR
from g2.infrastructure.logger import logger


def create_schema(db: sqlite3.Connection) -> None:
    """Create all tables and indexes. Safe to call multiple times (IF NOT EXISTS)."""
    db.executescript("""
        CREATE TABLE IF NOT EXISTS chats (
            jid TEXT PRIMARY KEY,
            name TEXT,
            last_message_time TEXT,
            channel TEXT,
            is_group INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS messages (
            id TEXT,
            chat_jid TEXT,
            sender TEXT,
            sender_name TEXT,
            content TEXT,
            timestamp TEXT,
            is_from_me INTEGER,
            is_bot_message INTEGER DEFAULT 0,
            PRIMARY KEY (id, chat_jid),
            FOREIGN KEY (chat_jid) REFERENCES chats(jid)
        );
        CREATE INDEX IF NOT EXISTS idx_timestamp ON messages(timestamp);

        CREATE TABLE IF NOT EXISTS scheduled_tasks (
            id TEXT PRIMARY KEY,
            group_folder TEXT NOT NULL,
            chat_jid TEXT NOT NULL,
            prompt TEXT NOT NULL,
            schedule_type TEXT NOT NULL,
            schedule_value TEXT NOT NULL,
            next_run TEXT,
            last_run TEXT,
            last_result TEXT,
            status TEXT DEFAULT 'active',
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_next_run ON scheduled_tasks(next_run);
        CREATE INDEX IF NOT EXISTS idx_status ON scheduled_tasks(status);

        CREATE TABLE IF NOT EXISTS task_run_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT NOT NULL,
            run_at TEXT NOT NULL,
            duration_ms INTEGER NOT NULL,
            status TEXT NOT NULL,
            result TEXT,
            error TEXT,
            FOREIGN KEY (task_id) REFERENCES scheduled_tasks(id)
        );
        CREATE INDEX IF NOT EXISTS idx_task_run_logs ON task_run_logs(task_id, run_at);

        CREATE TABLE IF NOT EXISTS router_state (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sessions (
            group_folder TEXT PRIMARY KEY,
            session_id TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS registered_groups (
            jid TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            folder TEXT NOT NULL UNIQUE,
            trigger_pattern TEXT NOT NULL,
            added_at TEXT NOT NULL,
            container_config TEXT,
            requires_trigger INTEGER DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS conversation_archives (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            group_folder TEXT NOT NULL,
            session_id TEXT NOT NULL,
            name TEXT NOT NULL,
            content TEXT NOT NULL DEFAULT '',
            archived_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_archives_group ON conversation_archives(group_folder);
    """)

    # Run migrations (safe to call multiple times)
    _run_schema_migrations(db)


def _run_schema_migrations(db: sqlite3.Connection) -> None:
    """Run ALTER TABLE migrations. Each is wrapped in try/except for idempotency."""

    # Migrate session_history -> conversation_archives
    try:
        row = db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='session_history'").fetchone()
        if row:
            db.execute("""
                INSERT INTO conversation_archives (group_folder, session_id, name, content, archived_at)
                SELECT group_folder, session_id, name, '', archived_at FROM session_history
            """)
            db.execute("DROP TABLE session_history")
            db.commit()
    except sqlite3.Error:
        pass

    # Add context_mode column
    try:
        db.execute("ALTER TABLE scheduled_tasks ADD COLUMN context_mode TEXT DEFAULT 'isolated'")
        db.commit()
    except sqlite3.OperationalError:
        pass

    # Add is_bot_message column
    try:
        db.execute("ALTER TABLE messages ADD COLUMN is_bot_message INTEGER DEFAULT 0")
        db.execute("UPDATE messages SET is_bot_message = 1 WHERE content LIKE ?", (f"{ASSISTANT_NAME}:%",))
        db.commit()
    except sqlite3.OperationalError:
        pass

    # Add channel and is_group columns
    try:
        db.execute("ALTER TABLE chats ADD COLUMN channel TEXT")
        db.execute("ALTER TABLE chats ADD COLUMN is_group INTEGER DEFAULT 0")
        db.execute("UPDATE chats SET channel = 'whatsapp', is_group = 1 WHERE jid LIKE '%@g.us'")
        db.execute("UPDATE chats SET channel = 'whatsapp', is_group = 0 WHERE jid LIKE '%@s.whatsapp.net'")
        db.execute("UPDATE chats SET channel = 'discord', is_group = 1 WHERE jid LIKE 'dc:%'")
        db.execute("UPDATE chats SET channel = 'telegram', is_group = 1 WHERE jid LIKE 'tg:%'")
        db.commit()
    except sqlite3.OperationalError:
        pass

    # Add channel column to registered_groups
    try:
        db.execute("ALTER TABLE registered_groups ADD COLUMN channel TEXT DEFAULT 'whatsapp'")
        db.commit()
    except sqlite3.OperationalError:
        pass

    # Add media columns to messages
    try:
        db.execute("ALTER TABLE messages ADD COLUMN media_type TEXT")
        db.execute("ALTER TABLE messages ADD COLUMN media_mimetype TEXT")
        db.execute("ALTER TABLE messages ADD COLUMN media_path TEXT")
        db.commit()
    except sqlite3.OperationalError:
        pass


def run_json_migrations(
    db: sqlite3.Connection,
    set_router_state: callable,
    set_session: callable,
    set_registered_group: callable,
) -> None:
    """Migrate legacy JSON state files to the database."""

    def migrate_file(filename: str) -> dict | list | None:
        file_path = DATA_DIR / filename
        if not file_path.exists():
            return None
        try:
            data = json.loads(file_path.read_text())
            file_path.rename(file_path.with_suffix(file_path.suffix + ".migrated"))
            return data
        except Exception:
            return None

    router_state = migrate_file("router_state.json")
    if router_state and isinstance(router_state, dict):
        if router_state.get("last_timestamp"):
            set_router_state("last_timestamp", router_state["last_timestamp"])
        if router_state.get("last_agent_timestamp"):
            set_router_state("last_agent_timestamp", json.dumps(router_state["last_agent_timestamp"]))

    sessions = migrate_file("sessions.json")
    if sessions and isinstance(sessions, dict):
        for folder, session_id in sessions.items():
            set_session(folder, session_id)

    groups = migrate_file("registered_groups.json")
    if groups and isinstance(groups, dict):
        for jid, group_data in groups.items():
            set_registered_group(jid, group_data)


class AppDatabase:
    """Composition root that initializes the DB and exposes repositories."""

    def __init__(self) -> None:
        self._db: sqlite3.Connection | None = None
        # Repositories are set after init
        self.chat_repo: MessageRepository | None = None  # type: ignore[assignment]
        self.message_repo: MessageRepository | None = None  # type: ignore[assignment]
        self.task_repo: TaskRepository | None = None  # type: ignore[assignment]
        self.session_repo: SessionRepository | None = None  # type: ignore[assignment]
        self.group_repo: GroupRepository | None = None  # type: ignore[assignment]
        self.state_repo: StateRepository | None = None  # type: ignore[assignment]

    @property
    def db(self) -> sqlite3.Connection:
        assert self._db is not None, "Database not initialized. Call init() first."
        return self._db

    def init(self) -> None:
        """Open (or create) the database file at the standard location."""
        db_path = STORE_DIR / "messages.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(db_path))
        self._db.row_factory = sqlite3.Row
        self._init_repos()

        run_json_migrations(
            self._db,
            set_router_state=lambda k, v: self.state_repo.set_router_state(k, v),
            set_session=lambda g, s: self.session_repo.set_session(g, s),
            set_registered_group=lambda j, g: self.group_repo.set_registered_group(j, g),
        )

    def _init_test(self) -> None:
        """For tests only. Creates a fresh in-memory database."""
        self._db = sqlite3.connect(":memory:")
        self._db.row_factory = sqlite3.Row
        self._init_repos()

    def _init_repos(self) -> None:
        assert self._db is not None
        create_schema(self._db)

        # Import here to avoid circular imports
        from g2.messaging.repository import MessageRepository
        from g2.groups.repository import GroupRepository
        from g2.sessions.repository import SessionRepository
        from g2.scheduling.repository import TaskRepository
        from g2.infrastructure.state_repo import StateRepository

        self.chat_repo = MessageRepository(self._db)
        self.message_repo = MessageRepository(self._db)
        self.task_repo = TaskRepository(self._db)
        self.session_repo = SessionRepository(self._db)
        self.group_repo = GroupRepository(self._db)
        self.state_repo = StateRepository(self._db)


# Singleton instance
database = AppDatabase()
