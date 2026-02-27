"""Tests for execution queue."""

import asyncio

import pytest

from g2.execution.execution_queue import GroupQueue, GroupState


class TestGroupQueue:
    def test_initial_state(self):
        queue = GroupQueue()
        assert queue._active_count == 0
        assert len(queue._groups) == 0

    def test_get_group_creates_state(self):
        queue = GroupQueue()
        state = queue._get_group("test@g.us")
        assert isinstance(state, GroupState)
        assert not state.active
        assert not state.pending_messages
        assert state.pending_tasks == []

    def test_get_group_returns_same_state(self):
        queue = GroupQueue()
        s1 = queue._get_group("test@g.us")
        s2 = queue._get_group("test@g.us")
        assert s1 is s2

    def test_enqueue_message_check_during_shutdown(self):
        queue = GroupQueue()
        queue._shutting_down = True
        queue.enqueue_message_check("test@g.us")
        assert "test@g.us" not in queue._groups

    def test_send_message_returns_false_when_inactive(self):
        queue = GroupQueue()
        assert queue.send_message("test@g.us", "hello") is False

    @pytest.mark.asyncio
    async def test_enqueue_and_process(self):
        queue = GroupQueue()
        processed = []

        async def process_fn(group_jid: str) -> bool:
            processed.append(group_jid)
            return True

        queue.set_process_messages_fn(process_fn)
        queue.enqueue_message_check("test@g.us")

        # Give the task time to run
        await asyncio.sleep(0.1)
        assert "test@g.us" in processed

    @pytest.mark.asyncio
    async def test_retry_on_failure(self):
        queue = GroupQueue()
        call_count = 0

        async def process_fn(group_jid: str) -> bool:
            nonlocal call_count
            call_count += 1
            return False  # Always fail

        queue.set_process_messages_fn(process_fn)
        queue.enqueue_message_check("test@g.us")

        await asyncio.sleep(0.2)
        assert call_count == 1  # First call happened

    @pytest.mark.asyncio
    async def test_queues_when_active(self):
        queue = GroupQueue()
        gate = asyncio.Event()
        calls = []

        async def process_fn(group_jid: str) -> bool:
            calls.append(group_jid)
            await gate.wait()
            return True

        queue.set_process_messages_fn(process_fn)
        queue.enqueue_message_check("test@g.us")

        await asyncio.sleep(0.05)
        # While first is running, enqueue another
        queue.enqueue_message_check("test@g.us")
        state = queue._get_group("test@g.us")
        assert state.pending_messages is True

        gate.set()
        await asyncio.sleep(0.1)

    @pytest.mark.asyncio
    async def test_shutdown(self):
        queue = GroupQueue()
        await queue.shutdown()
        assert queue._shutting_down is True
