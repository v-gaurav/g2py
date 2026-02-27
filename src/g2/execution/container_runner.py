"""ContainerRunner — spawns agent containers via async subprocess."""

from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass
from typing import Callable, Awaitable

from g2.execution.container_runtime import ContainerRuntime, DockerRuntime
from g2.execution.mount_builder import DefaultMountFactory, MountFactory
from g2.execution.output_parser import ContainerOutput, ContainerOutputParser
from g2.groups.types import RegisteredGroup
from g2.infrastructure.config import (
    CONTAINER_IMAGE,
    CONTAINER_TIMEOUT,
    IDLE_TIMEOUT,
    TimeoutConfig,
    read_env_file,
)
from g2.infrastructure.logger import logger


@dataclass
class ContainerInput:
    prompt: str
    session_id: str | None
    group_folder: str
    chat_jid: str
    is_main: bool
    is_scheduled_task: bool = False


OnProcess = Callable[[asyncio.subprocess.Process, str], None]
OnOutput = Callable[[ContainerOutput], Awaitable[None]]


class ContainerRunner:
    """Runs agent containers and streams output."""

    def __init__(
        self,
        runtime: ContainerRuntime | None = None,
        mount_factory: MountFactory | None = None,
        timeout_config: TimeoutConfig | None = None,
    ) -> None:
        self._runtime = runtime or DockerRuntime()
        self._mount_factory = mount_factory or DefaultMountFactory()
        self._timeout = timeout_config or TimeoutConfig()

    async def run(
        self,
        group: RegisteredGroup,
        input_data: ContainerInput,
        on_process: OnProcess | None = None,
        on_output: OnOutput | None = None,
    ) -> ContainerOutput:
        """Run a container and return the final output."""
        container_name = f"g2-{group.folder}-{int(time.time())}"
        is_main = input_data.is_main

        mount_args = self._mount_factory.build_mounts(group, is_main)
        timeout = self._timeout.for_group(group)

        # Read secrets from .env
        secret_keys = ["ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN"]
        secrets = read_env_file(secret_keys)

        env_args: list[str] = []
        for key, value in secrets.items():
            env_args.extend(["-e", f"{key}={value}"])

        # Group-specific env vars
        env_args.extend(["-e", f"G2_GROUP_FOLDER={group.folder}"])
        env_args.extend(["-e", f"G2_IS_MAIN={'1' if is_main else '0'}"])
        env_args.extend(["-e", f"G2_CHAT_JID={input_data.chat_jid}"])

        container_args = [
            "run", "-i", "--rm",
            "--name", container_name,
            *mount_args,
            *env_args,
            CONTAINER_IMAGE,
        ]

        logger.info(
            "Starting container",
            name=container_name,
            group=group.name,
            image=CONTAINER_IMAGE,
        )

        proc = await asyncio.create_subprocess_exec(
            self._runtime.bin, *container_args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        if on_process:
            on_process(proc, container_name)

        # Write input JSON to stdin
        stdin_data = json.dumps({
            "prompt": input_data.prompt,
            "sessionId": input_data.session_id,
            "groupFolder": input_data.group_folder,
            "chatJid": input_data.chat_jid,
            "isMain": input_data.is_main,
            "isScheduledTask": input_data.is_scheduled_task,
            "secrets": secrets,
        }).encode()

        assert proc.stdin is not None
        proc.stdin.write(stdin_data)
        proc.stdin.write_eof()

        # Stream stdout and parse output
        parser = ContainerOutputParser()
        last_output = ContainerOutput(status="success", result=None)

        async def read_stdout() -> None:
            nonlocal last_output
            assert proc.stdout is not None
            async for raw_line in proc.stdout:
                line = raw_line.decode(errors="replace")
                output = parser.feed(line)
                if output:
                    last_output = output
                    if on_output:
                        await on_output(output)

        async def read_stderr() -> None:
            assert proc.stderr is not None
            async for raw_line in proc.stderr:
                line = raw_line.decode(errors="replace").rstrip()
                if line:
                    logger.debug("Container stderr", name=container_name, line=line)

        # Run stdout/stderr readers and wait for process to finish
        hard_timeout_s = timeout.get_hard_timeout() / 1000

        try:
            await asyncio.wait_for(
                asyncio.gather(read_stdout(), read_stderr(), proc.wait()),
                timeout=hard_timeout_s,
            )
        except asyncio.TimeoutError:
            logger.warning("Container hard timeout, killing", name=container_name)
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            last_output = ContainerOutput(status="error", error="Container timeout")

        return_code = proc.returncode
        if return_code and return_code != 0 and last_output.status != "error":
            logger.warning("Container exited with error", name=container_name, code=return_code)

        logger.info("Container finished", name=container_name, status=last_output.status)
        return last_output
