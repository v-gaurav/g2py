"""File-based IPC write operations."""

from __future__ import annotations

import json
import os
import time
import random
import string

from g2.groups.paths import GroupPaths
from g2.infrastructure.logger import logger


class IpcTransport:
    """Handles file-based IPC communication with containers.

    Writes message files and close sentinels to the container's input directory.
    Uses atomic write (tmp + rename) to prevent partial reads.
    """

    def send_message(self, group_folder: str, text: str) -> bool:
        """Write a message file for the container to read."""
        input_dir = GroupPaths.ipc_input_dir(group_folder)
        try:
            input_dir.mkdir(parents=True, exist_ok=True)
            rand = "".join(random.choices(string.ascii_lowercase + string.digits, k=4))
            filename = f"{int(time.time() * 1000)}-{rand}.json"
            filepath = input_dir / filename
            temp_path = filepath.with_suffix(".json.tmp")
            temp_path.write_text(json.dumps({"type": "message", "text": text}))
            temp_path.rename(filepath)
            return True
        except Exception as err:
            logger.warning("Failed to send follow-up via IPC", error=str(err), group_folder=group_folder)
            return False

    def close_stdin(self, group_folder: str) -> None:
        """Write a close sentinel file to signal the container to wind down."""
        input_dir = GroupPaths.ipc_input_dir(group_folder)
        try:
            input_dir.mkdir(parents=True, exist_ok=True)
            (input_dir / "_close").write_text("")
        except Exception as err:
            logger.warning("Failed to write close sentinel", error=str(err), group_folder=group_folder)
