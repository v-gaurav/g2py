"""Orchestrator class — composes services, wires subsystems."""

from __future__ import annotations

import asyncio
import os
import signal
from pathlib import Path

from g2.execution.agent_executor import AgentExecutor
from g2.execution.container_runner import ContainerRunner
from g2.execution.execution_queue import GroupQueue
from g2.groups.types import RegisteredGroup
from g2.infrastructure.config import (
    DATA_DIR,
    GMAIL_GROUP_FOLDER,
    GMAIL_POLL_INTERVAL,
    GMAIL_TRIGGER_ADDRESS,
    GROUPS_DIR,
    STORE_DIR,
)
from g2.infrastructure.database import AppDatabase, database
from g2.infrastructure.logger import logger
from g2.ipc.transport import IpcTransport
from g2.ipc.watcher import IpcDeps, IpcWatcher
from g2.messaging.channel_registry import ChannelRegistry
from g2.messaging.poller import MessageProcessor
from g2.messaging.repository import MessageRepository
from g2.messaging.types import NewMessage
from g2.scheduling.scheduler import SchedulerDependencies, start_scheduler_loop
from g2.scheduling.snapshot_writer import AvailableGroup, SnapshotWriter
from g2.scheduling.task_service import TaskManager
from g2.sessions.manager import SessionManager


class Orchestrator:
    """Composes all services and manages the application lifecycle."""

    def __init__(self) -> None:
        self._db: AppDatabase = database
        self._channel_registry = ChannelRegistry()
        self._transport = IpcTransport()
        self._queue = GroupQueue(transport=self._transport)
        self._ipc_watcher = IpcWatcher()
        self._running = False
        self._registered_groups: dict[str, RegisteredGroup] = {}
        self._poll_handle = None
        self._scheduler_handle = None

    async def start(self) -> None:
        """Initialize all services and start the event loop."""
        logger.info("Starting G2...")

        # Initialize database
        self._db.init()

        # Load registered groups
        self._registered_groups = self._db.group_repo.get_all_registered_groups()
        logger.info("Loaded registered groups", count=len(self._registered_groups))

        # Initialize session manager
        session_manager = SessionManager(self._db.session_repo)
        session_manager.load_from_db()

        # Initialize task manager and snapshot writer
        task_manager = TaskManager(self._db.task_repo)
        snapshot_writer = SnapshotWriter(task_manager)

        # Initialize container runner and agent executor
        container_runner = ContainerRunner()
        agent_executor = AgentExecutor(
            session_manager=session_manager,
            queue=self._queue,
            get_available_groups=self._get_available_groups,
            get_registered_groups=lambda: self._registered_groups,
            snapshot_writer=snapshot_writer,
            container_runner=container_runner,
        )

        # Initialize message processor
        message_processor = MessageProcessor(
            registered_groups=lambda: self._registered_groups,
            channel_registry=self._channel_registry,
            queue=self._queue,
            agent_executor=agent_executor,
            state_repo=self._db.state_repo,
            message_repo=self._db.message_repo,
        )
        message_processor.load_state()

        # Wire up the queue to use message processor
        self._queue.set_process_messages_fn(message_processor.process_group_messages)

        # Set up channels
        await self._setup_channels(message_processor)

        # Start IPC watcher
        ipc_deps = IpcDeps(
            send_message=self._send_message,
            send_media=self._send_media,
            registered_groups=lambda: self._registered_groups,
            register_group=self._register_group,
            sync_group_metadata=self._channel_registry.sync_all_metadata,
            get_available_groups=self._get_available_groups,
            write_groups_snapshot=snapshot_writer.write_groups,
            session_manager=session_manager,
            close_stdin=self._queue.close_stdin,
            task_manager=task_manager,
        )
        self._ipc_watcher.start(ipc_deps)

        # Start scheduler
        scheduler_deps = SchedulerDependencies(
            registered_groups=lambda: self._registered_groups,
            get_sessions=session_manager.get_all,
            queue=self._queue,
            send_message=self._send_message,
            task_manager=task_manager,
            snapshot_writer=snapshot_writer,
            container_runner=container_runner,
        )
        self._scheduler_handle = start_scheduler_loop(scheduler_deps)

        # Start message polling
        self._poll_handle = message_processor.start_polling()

        # Recover pending messages from before shutdown
        message_processor.recover_pending_messages()

        self._running = True
        logger.info("G2 started successfully")

    async def _setup_channels(self, message_processor: MessageProcessor) -> None:
        """Set up WhatsApp and Gmail channels."""

        def on_message(chat_jid: str, msg: NewMessage) -> None:
            self._db.message_repo.store_message(msg)

        def on_chat_metadata(jid: str, timestamp: str, name: str | None, channel: str | None, is_group: bool | None) -> None:
            self._db.message_repo.upsert_chat(jid, timestamp, name, channel, is_group)

        # WhatsApp channel
        try:
            from g2.messaging.whatsapp.channel import WhatsAppChannel

            wa_channel = WhatsAppChannel(
                on_message=on_message,
                on_chat_metadata=on_chat_metadata,
                registered_groups=lambda: self._registered_groups,
                chat_repo=self._db.message_repo,
            )
            await wa_channel.connect()
            self._channel_registry.register(wa_channel)
            logger.info("WhatsApp channel registered")
        except Exception:
            logger.exception("Failed to set up WhatsApp channel")

        # Gmail channel (optional)
        gmail_creds = Path.home() / ".gmail-mcp" / "credentials.json"
        if gmail_creds.exists():
            try:
                from g2.messaging.gmail.channel import GmailChannel

                gmail_channel = GmailChannel(
                    on_message=on_message,
                    on_chat_metadata=on_chat_metadata,
                    registered_groups=lambda: self._registered_groups,
                    trigger_address=GMAIL_TRIGGER_ADDRESS,
                    poll_interval_ms=int(GMAIL_POLL_INTERVAL * 1000),
                    group_folder=GMAIL_GROUP_FOLDER,
                )
                await gmail_channel.connect()
                self._channel_registry.register(gmail_channel)
                logger.info("Gmail channel registered")
            except Exception:
                logger.exception("Failed to set up Gmail channel")

    async def _send_message(self, jid: str, text: str) -> None:
        channel = self._channel_registry.find_connected_by_jid(jid)
        if channel:
            await channel.send_message(jid, text)
        else:
            logger.warning("No connected channel for JID", jid=jid)

    async def _send_media(
        self, jid: str, file_path: str, media_type: str, caption: str | None = None, mimetype: str | None = None
    ) -> None:
        channel = self._channel_registry.find_connected_by_jid(jid)
        if channel and hasattr(channel, "send_media"):
            await channel.send_media(jid, file_path, media_type, caption, mimetype)
        else:
            logger.warning("No connected channel for media", jid=jid)

    def _register_group(self, jid: str, group: RegisteredGroup) -> None:
        self._registered_groups[jid] = group
        self._db.group_repo.set_registered_group(jid, group)
        # Ensure group directory exists
        (GROUPS_DIR / group.folder).mkdir(parents=True, exist_ok=True)

    def _get_available_groups(self) -> list[AvailableGroup]:
        """Get all known chats as available groups."""
        chats = self._db.message_repo.get_all_chats()
        return [
            AvailableGroup(
                jid=chat["jid"],
                name=chat.get("name", ""),
                last_activity=chat.get("last_message_time", ""),
                is_registered=chat["jid"] in self._registered_groups,
            )
            for chat in chats
            if chat.get("is_group")
        ]

    async def shutdown(self) -> None:
        """Gracefully shut down all services."""
        logger.info("Shutting down G2...")
        self._running = False

        if self._poll_handle:
            self._poll_handle.stop()
        if self._scheduler_handle:
            self._scheduler_handle.stop()

        self._ipc_watcher.stop()
        await self._queue.shutdown()
        await self._channel_registry.disconnect_all()

        logger.info("G2 shut down complete")
