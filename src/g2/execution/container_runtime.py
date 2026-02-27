"""Container runtime abstraction — Protocol + Docker implementation."""

from __future__ import annotations

import shutil
from typing import Protocol


class ContainerRuntime(Protocol):
    """Interface for container runtimes (Docker, Podman, etc.)."""

    @property
    def bin(self) -> str:
        """Path to the runtime binary (e.g. 'docker')."""
        ...

    @property
    def socket(self) -> str:
        """Path to the runtime socket."""
        ...


class DockerRuntime:
    """Docker container runtime."""

    def __init__(self) -> None:
        self._bin = shutil.which("docker") or "docker"

    @property
    def bin(self) -> str:
        return self._bin

    @property
    def socket(self) -> str:
        return "/var/run/docker.sock"
