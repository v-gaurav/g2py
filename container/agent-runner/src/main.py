"""G2 Agent Runner — runs inside Docker containers.

Reads JSON from stdin, invokes Claude via claude CLI or Anthropic SDK,
polls for follow-up messages via IPC, and streams output via sentinel markers.
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import sys
import time
from pathlib import Path
from typing import Any


# --- Constants ---

OUTPUT_START = "---G2_OUTPUT_START---"
OUTPUT_END = "---G2_OUTPUT_END---"

IPC_INPUT_DIR = Path("/workspace/ipc/input")
IPC_MESSAGES_DIR = Path("/workspace/ipc/messages")
IPC_TASKS_DIR = Path("/workspace/ipc/tasks")
WORKSPACE_GROUP = Path("/workspace/group")
CLOSE_SENTINEL = "_close"
MESSAGE_POLL_INTERVAL = 1.0  # seconds


# --- Output helpers ---


def emit_output(result: str | None = None, new_session_id: str | None = None, status: str = "success", error: str | None = None) -> None:
    """Emit a result block between OUTPUT_START and OUTPUT_END markers."""
    payload: dict[str, Any] = {"status": status}
    if result is not None:
        payload["result"] = result
    if new_session_id is not None:
        payload["newSessionId"] = new_session_id
    if error is not None:
        payload["error"] = error

    print(OUTPUT_START, flush=True)
    print(json.dumps(payload), flush=True)
    print(OUTPUT_END, flush=True)


def emit_error(error: str) -> None:
    emit_output(status="error", error=error)


# --- Input parsing ---


def read_stdin_input() -> dict[str, Any]:
    """Read and parse JSON input from stdin."""
    raw = sys.stdin.read()
    if not raw.strip():
        raise ValueError("Empty stdin input")
    return json.loads(raw)


# --- IPC message stream ---


class MessageStream:
    """Polls /workspace/ipc/input/ for follow-up messages and close sentinel."""

    def __init__(self) -> None:
        self._closed = False
        self._processed: set[str] = set()

    @property
    def is_closed(self) -> bool:
        return self._closed

    def poll(self) -> str | None:
        """Poll for new messages. Returns message content or None."""
        if not IPC_INPUT_DIR.exists():
            return None

        messages: list[tuple[float, str, Path]] = []

        for f in IPC_INPUT_DIR.iterdir():
            if not f.is_file():
                continue

            if f.name == CLOSE_SENTINEL:
                self._closed = True
                try:
                    f.unlink()
                except OSError:
                    pass
                return None

            if f.name in self._processed:
                continue

            try:
                mtime = f.stat().st_mtime
                content = f.read_text().strip()
                if content:
                    messages.append((mtime, content, f))
                self._processed.add(f.name)
            except OSError:
                continue

        if not messages:
            return None

        messages.sort(key=lambda x: x[0])
        combined = "\n".join(content for _, content, _ in messages)
        return combined


# --- Claude invocation ---


async def run_claude_code(
    prompt: str,
    session_id: str | None,
    group_folder: str,
    is_main: bool,
    secrets: dict[str, str] | None = None,
    is_scheduled_task: bool = False,
) -> tuple[str | None, str | None]:
    """Run Claude Code CLI and return (result, new_session_id).

    Uses claude CLI with --print flag for non-interactive mode.
    Falls back to direct Anthropic SDK if claude CLI is not available.
    """
    # Set up environment
    env = dict(os.environ)

    # Pass secrets as environment variables
    if secrets:
        for key, value in secrets.items():
            env[key] = value

    # Build claude command
    cmd = ["claude", "--print", "--dangerously-skip-permissions"]

    if session_id:
        cmd.extend(["--resume", session_id])

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
        cwd=str(WORKSPACE_GROUP),
    )

    stdout_data, stderr_data = await proc.communicate(input=prompt.encode())

    result = stdout_data.decode().strip() if stdout_data else None
    new_session_id = None

    # Try to extract session ID from stderr (claude CLI outputs it there)
    if stderr_data:
        stderr_text = stderr_data.decode()
        for line in stderr_text.splitlines():
            if "session:" in line.lower() or "session_id:" in line.lower():
                parts = line.split(":")
                if len(parts) >= 2:
                    new_session_id = parts[-1].strip()
                    break

    return result, new_session_id


async def run_with_followups(
    initial_prompt: str,
    session_id: str | None,
    group_folder: str,
    is_main: bool,
    secrets: dict[str, str] | None = None,
    is_scheduled_task: bool = False,
) -> None:
    """Run Claude with follow-up message support.

    After the initial invocation, polls for follow-up messages and
    re-invokes Claude with the new context. Exits when close sentinel
    is received or no new messages arrive.
    """
    stream = MessageStream()
    current_session_id = session_id

    # Run initial prompt
    try:
        result, new_sid = await run_claude_code(
            initial_prompt,
            current_session_id,
            group_folder,
            is_main,
            secrets,
            is_scheduled_task,
        )

        if new_sid:
            current_session_id = new_sid

        emit_output(result=result, new_session_id=current_session_id)
    except Exception as err:
        emit_error(str(err))
        return

    if is_scheduled_task:
        return

    # Poll for follow-up messages
    while not stream.is_closed:
        await asyncio.sleep(MESSAGE_POLL_INTERVAL)

        msg = stream.poll()
        if stream.is_closed:
            break
        if not msg:
            continue

        try:
            result, new_sid = await run_claude_code(
                msg,
                current_session_id,
                group_folder,
                is_main,
                secrets,
            )

            if new_sid:
                current_session_id = new_sid

            emit_output(result=result, new_session_id=current_session_id)
        except Exception as err:
            emit_error(str(err))


# --- Main entry point ---


async def main() -> None:
    try:
        input_data = read_stdin_input()
    except (json.JSONDecodeError, ValueError) as err:
        emit_error(f"Invalid input: {err}")
        sys.exit(1)

    prompt = input_data.get("prompt", "")
    session_id = input_data.get("sessionId")
    group_folder = input_data.get("groupFolder", "")
    chat_jid = input_data.get("chatJid", "")
    is_main = input_data.get("isMain", False)
    secrets = input_data.get("secrets")
    is_scheduled_task = input_data.get("isScheduledTask", False)

    if not prompt:
        emit_error("No prompt provided")
        sys.exit(1)

    # Set up signal handlers for graceful shutdown
    shutdown = asyncio.Event()

    def on_signal() -> None:
        shutdown.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, on_signal)

    # Ensure IPC directories exist
    for d in (IPC_INPUT_DIR, IPC_MESSAGES_DIR, IPC_TASKS_DIR):
        d.mkdir(parents=True, exist_ok=True)

    await run_with_followups(
        prompt,
        session_id,
        group_folder,
        is_main,
        secrets,
        is_scheduled_task,
    )


if __name__ == "__main__":
    asyncio.run(main())
