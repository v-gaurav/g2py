"""Group IPC handlers: register_group, refresh_groups."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from g2.groups.authorization import AuthContext, AuthorizationPolicy
from g2.groups.types import ContainerConfig, RegisteredGroup
from g2.infrastructure.logger import logger
from g2.ipc.dispatcher import HandlerContext, IpcCommandHandler, IpcHandlerError


# --- RegisterGroupHandler ---


@dataclass
class RegisterGroupPayload:
    jid: str
    name: str
    folder: str
    trigger: str
    channel: str | None
    container_config: dict | None
    requires_trigger: bool | None


class RegisterGroupHandler(IpcCommandHandler):
    command = "register_group"

    async def validate(self, data: dict[str, Any]) -> RegisterGroupPayload:
        if not data.get("jid") or not data.get("name") or not data.get("folder") or not data.get("trigger"):
            raise IpcHandlerError("Missing required fields", {"command": self.command})
        return RegisterGroupPayload(
            jid=data["jid"],
            name=data["name"],
            folder=data["folder"],
            trigger=data["trigger"],
            channel=data.get("channel"),
            container_config=data.get("containerConfig"),
            requires_trigger=data.get("requiresTrigger"),
        )

    async def execute(self, payload: RegisterGroupPayload, context: HandlerContext) -> None:
        auth = AuthorizationPolicy(AuthContext(source_group=context.source_group, is_main=context.is_main))
        if not auth.can_register_group():
            raise IpcHandlerError("Unauthorized register_group attempt", {"sourceGroup": context.source_group})

        container_config = None
        if payload.container_config:
            container_config = ContainerConfig(**payload.container_config)

        context.deps.register_group(
            payload.jid,
            RegisteredGroup(
                name=payload.name,
                folder=payload.folder,
                trigger=payload.trigger,
                added_at=datetime.now().isoformat(),
                channel=payload.channel or "whatsapp",
                container_config=container_config,
                requires_trigger=payload.requires_trigger,
            ),
        )

        logger.info("Group registered via IPC", source_group=context.source_group, jid=payload.jid, folder=payload.folder)


# --- RefreshGroupsHandler ---


class RefreshGroupsHandler(IpcCommandHandler):
    command = "refresh_groups"

    async def validate(self, data: dict[str, Any]) -> None:
        return None

    async def execute(self, _payload: None, context: HandlerContext) -> None:
        auth = AuthorizationPolicy(AuthContext(source_group=context.source_group, is_main=context.is_main))
        if not auth.can_refresh_groups():
            raise IpcHandlerError("Unauthorized refresh_groups attempt", {"sourceGroup": context.source_group})

        logger.info("Group metadata refresh requested via IPC", source_group=context.source_group)
        await context.deps.sync_group_metadata(True)
        registered_groups = context.deps.registered_groups()
        available_groups = context.deps.get_available_groups()
        context.deps.write_groups_snapshot(
            context.source_group, True, available_groups, set(registered_groups.keys())
        )
