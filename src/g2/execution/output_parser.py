"""Stateful parser for OUTPUT_START/END marker protocol."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

OUTPUT_START_MARKER = "---G2_OUTPUT_START---"
OUTPUT_END_MARKER = "---G2_OUTPUT_END---"


@dataclass
class ContainerOutput:
    status: str = "success"
    result: str | None = None
    new_session_id: str | None = None
    error: str | None = None


class ContainerOutputParser:
    """Stateful parser that accumulates lines between OUTPUT_START and OUTPUT_END markers.

    Calls the callback with each complete ContainerOutput.
    """

    def __init__(self) -> None:
        self._collecting = False
        self._buffer: list[str] = []

    def feed(self, line: str) -> ContainerOutput | None:
        """Feed a line of stdout. Returns a ContainerOutput if a complete block was parsed."""
        stripped = line.rstrip("\n").rstrip("\r")

        if stripped == OUTPUT_START_MARKER:
            self._collecting = True
            self._buffer = []
            return None

        if stripped == OUTPUT_END_MARKER:
            self._collecting = False
            raw = "\n".join(self._buffer)
            self._buffer = []
            return self._parse_output(raw)

        if self._collecting:
            self._buffer.append(stripped)

        return None

    def _parse_output(self, raw: str) -> ContainerOutput:
        try:
            data = json.loads(raw)
            return ContainerOutput(
                status=data.get("status", "success"),
                result=data.get("result"),
                new_session_id=data.get("newSessionId"),
                error=data.get("error"),
            )
        except (json.JSONDecodeError, TypeError):
            return ContainerOutput(status="error", error=f"Failed to parse output: {raw[:200]}")
