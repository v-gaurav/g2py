"""Mount factory for building Docker mount arguments."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from g2.execution.mount_security import MountAllowlist, load_mount_allowlist, validate_mount
from g2.groups.paths import GroupPaths
from g2.groups.types import AdditionalMount, RegisteredGroup
from g2.infrastructure.config import CONTAINER_IMAGE, DATA_DIR, GROUPS_DIR, MAIN_GROUP_FOLDER
from g2.infrastructure.logger import logger


class MountFactory(Protocol):
    """Interface for building container mount arguments."""

    def build_mounts(self, group: RegisteredGroup, is_main: bool) -> list[str]: ...


class DefaultMountFactory:
    """Builds Docker -v mount arguments for container execution."""

    def __init__(self) -> None:
        self._allowlist = load_mount_allowlist()

    def build_mounts(self, group: RegisteredGroup, is_main: bool) -> list[str]:
        mounts: list[str] = []
        group_dir = GroupPaths.group_dir(group.folder)
        group_dir.mkdir(parents=True, exist_ok=True)

        # Mount group's directory as /workspace/group
        mounts.extend(["-v", f"{group_dir}:/workspace/group"])

        # Mount IPC directories
        ipc_dir = GroupPaths.ipc_dir(group.folder)
        ipc_dir.mkdir(parents=True, exist_ok=True)
        mounts.extend(["-v", f"{ipc_dir}:/workspace/ipc"])

        # Mount main group's CLAUDE.md as global context (for non-main groups)
        if not is_main:
            main_claude_md = GROUPS_DIR / MAIN_GROUP_FOLDER / "CLAUDE.md"
            if main_claude_md.exists():
                mounts.extend(["-v", f"{main_claude_md}:/workspace/global/CLAUDE.md:ro"])

        # Mount sessions directory
        sessions_dir = GroupPaths.sessions_dir(group.folder)
        sessions_dir.mkdir(parents=True, exist_ok=True)
        mounts.extend(["-v", f"{sessions_dir}:/home/node/.claude"])

        # Process additional mounts from container config
        if group.container_config and group.container_config.additional_mounts:
            for mount in group.container_config.additional_mounts:
                self._add_validated_mount(mounts, mount, is_main)

        return mounts

    def _add_validated_mount(
        self, mounts: list[str], mount: AdditionalMount, is_main: bool
    ) -> None:
        host_path = str(Path(mount.host_path).expanduser().resolve())

        allowed, force_ro = validate_mount(host_path, self._allowlist, is_main)
        if not allowed:
            logger.warning("Mount blocked by allowlist", host_path=host_path)
            return

        container_path = mount.container_path or f"/workspace/extra/{Path(host_path).name}"
        read_only = mount.readonly or force_ro
        ro_suffix = ":ro" if read_only else ""

        mounts.extend(["-v", f"{host_path}:{container_path}{ro_suffix}"])
