"""Message processor — poll loop, cursor management, trigger checking."""

from __future__ import annotations

import json
import re
from typing import Callable, Awaitable

from g2.execution.agent_executor import AgentExecutor
from g2.execution.execution_queue import GroupQueue
from g2.execution.output_parser import ContainerOutput
from g2.groups.types import RegisteredGroup
from g2.infrastructure.config import ASSISTANT_NAME, IDLE_TIMEOUT, MAIN_GROUP_FOLDER, POLL_INTERVAL
from g2.infrastructure.idle_timer import IdleTimer
from g2.infrastructure.logger import logger
from g2.infrastructure.poll_loop import PollLoop, start_poll_loop
from g2.infrastructure.state_repo import StateRepository
from g2.messaging.channel_registry import ChannelRegistry
from g2.messaging.formatter import format_messages, strip_internal_tags
from g2.messaging.repository import MessageRepository
from g2.messaging.types import NewMessage


def has_trigger(messages: list[NewMessage], group: RegisteredGroup) -> bool:
    """Check if any message matches the group's trigger pattern."""
    if group.requires_trigger is False:
        return True
    pattern = re.compile(group.trigger, re.IGNORECASE)
    return any(pattern.search(m.content.strip()) for m in messages)


class MessageProcessor:
    """Polls for new messages and dispatches them to agent containers."""

    def __init__(
        self,
        registered_groups: Callable[[], dict[str, RegisteredGroup]],
        channel_registry: ChannelRegistry,
        queue: GroupQueue,
        agent_executor: AgentExecutor,
        state_repo: StateRepository,
        message_repo: MessageRepository,
    ) -> None:
        self._registered_groups = registered_groups
        self._channel_registry = channel_registry
        self._queue = queue
        self._agent_executor = agent_executor
        self._state_repo = state_repo
        self._message_repo = message_repo
        self._last_timestamp = ""
        self._last_agent_timestamp: dict[str, str] = {}

    def load_state(self) -> None:
        self._last_timestamp = self._state_repo.get_router_state("last_timestamp") or ""
        raw = self._state_repo.get_router_state("last_agent_timestamp")
        if raw:
            try:
                self._last_agent_timestamp = json.loads(raw)
            except json.JSONDecodeError:
                logger.warning("Corrupted last_agent_timestamp in DB, resetting")
                self._last_agent_timestamp = {}
        else:
            self._last_agent_timestamp = {}

    def save_state(self) -> None:
        self._state_repo.set_router_state("last_timestamp", self._last_timestamp)
        self._state_repo.set_router_state("last_agent_timestamp", json.dumps(self._last_agent_timestamp))

    def start_polling(self) -> PollLoop:
        logger.info(f"G2 running (trigger: @{ASSISTANT_NAME})")

        async def poll() -> None:
            jids = list(self._registered_groups().keys())
            messages, new_ts = self._message_repo.get_new_messages(jids, self._last_timestamp, ASSISTANT_NAME)

            if not messages:
                return

            logger.info("New messages", count=len(messages))

            self._last_timestamp = new_ts
            self.save_state()

            # Deduplicate by group
            messages_by_group: dict[str, list[NewMessage]] = {}
            for msg in messages:
                messages_by_group.setdefault(msg.chat_jid, []).append(msg)

            for chat_jid, group_messages in messages_by_group.items():
                group = self._registered_groups().get(chat_jid)
                if not group:
                    continue

                channel = self._channel_registry.find_by_jid(chat_jid)
                if not channel:
                    logger.warning(f"No channel owns JID {chat_jid}, skipping")
                    continue

                is_main = group.folder == MAIN_GROUP_FOLDER

                if not is_main and not has_trigger(group_messages, group):
                    continue

                # Pull all messages since last agent timestamp
                all_pending = self._message_repo.get_messages_since(
                    chat_jid, self._last_agent_timestamp.get(chat_jid, ""), ASSISTANT_NAME
                )
                messages_to_send = all_pending if all_pending else group_messages
                formatted = format_messages(messages_to_send)

                if self._queue.send_message(chat_jid, formatted):
                    logger.debug("Piped messages to active container", chat_jid=chat_jid, count=len(messages_to_send))
                    self._last_agent_timestamp[chat_jid] = messages_to_send[-1].timestamp
                    self.save_state()
                    await channel.set_typing(chat_jid, True)
                else:
                    self._queue.enqueue_message_check(chat_jid)

        return start_poll_loop("Message", POLL_INTERVAL, poll)

    async def process_group_messages(self, chat_jid: str) -> bool:
        """Process accumulated messages for a group. Called by the execution queue."""
        group = self._registered_groups().get(chat_jid)
        if not group:
            return True

        channel = self._channel_registry.find_by_jid(chat_jid)
        if not channel:
            logger.warning(f"No channel owns JID {chat_jid}, skipping")
            return True

        since = self._last_agent_timestamp.get(chat_jid, "")
        missed = self._message_repo.get_messages_since(chat_jid, since, ASSISTANT_NAME)

        if not missed:
            return True

        prompt = format_messages(missed)

        previous_cursor = self._last_agent_timestamp.get(chat_jid, "")
        self._last_agent_timestamp[chat_jid] = missed[-1].timestamp
        self.save_state()

        logger.info("Processing messages", group=group.name, count=len(missed))

        idle = IdleTimer(
            lambda: (logger.debug("Idle timeout, closing container stdin", group=group.name), self._queue.close_stdin(chat_jid)),
            IDLE_TIMEOUT / 1000,
        )

        await channel.set_typing(chat_jid, True)
        had_error = False
        output_sent = False

        async def on_output(result: ContainerOutput) -> None:
            nonlocal had_error, output_sent
            if result.result:
                raw = result.result if isinstance(result.result, str) else json.dumps(result.result)
                text = strip_internal_tags(raw)
                logger.info("Agent output", group=group.name, preview=raw[:200])
                if text:
                    await channel.send_message(chat_jid, text)
                    output_sent = True
                idle.reset()
            if result.status == "error":
                had_error = True

        output = await self._agent_executor.execute(group, prompt, chat_jid, on_output)

        await channel.set_typing(chat_jid, False)
        idle.clear()

        if output == "error" or had_error:
            if output_sent:
                logger.warning("Agent error after output sent, skipping cursor rollback", group=group.name)
                return True
            self._last_agent_timestamp[chat_jid] = previous_cursor
            self.save_state()
            logger.warning("Agent error, rolled back cursor for retry", group=group.name)
            return False

        return True

    def recover_pending_messages(self) -> None:
        """Re-enqueue unprocessed messages from before shutdown."""
        for chat_jid, group in self._registered_groups().items():
            since = self._last_agent_timestamp.get(chat_jid, "")
            pending = self._message_repo.get_messages_since(chat_jid, since, ASSISTANT_NAME)
            if not pending:
                continue
            is_main = group.folder == MAIN_GROUP_FOLDER
            if not is_main and not has_trigger(pending, group):
                continue
            logger.info("Recovery: found unprocessed messages", group=group.name, count=len(pending))
            self._queue.enqueue_message_check(chat_jid)
