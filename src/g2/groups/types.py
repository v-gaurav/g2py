"""Group domain types."""

from __future__ import annotations

from pydantic import BaseModel


class AdditionalMount(BaseModel):
    host_path: str  # Absolute path on host (supports ~ for home)
    container_path: str | None = None  # Optional — defaults to basename of host_path
    readonly: bool = True  # Default: true for safety


class AllowedRoot(BaseModel):
    path: str  # Absolute path or ~ for home
    allow_read_write: bool = False
    description: str | None = None


class MountAllowlist(BaseModel):
    allowed_roots: list[AllowedRoot]
    blocked_patterns: list[str]
    non_main_read_only: bool = True


class ContainerConfig(BaseModel):
    additional_mounts: list[AdditionalMount] | None = None
    timeout: int | None = None  # Default: 300000 (5 minutes)


class RegisteredGroup(BaseModel):
    name: str
    folder: str
    trigger: str
    added_at: str
    channel: str = "whatsapp"
    container_config: ContainerConfig | None = None
    requires_trigger: bool | None = True  # Default: true for groups, false for solo chats
