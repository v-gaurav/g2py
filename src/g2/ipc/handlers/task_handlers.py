"""Task IPC handlers: schedule, pause, resume, cancel."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from g2.groups.authorization import AuthContext, AuthorizationPolicy
from g2.infrastructure.logger import logger
from g2.ipc.dispatcher import HandlerContext, IpcCommandHandler, IpcHandlerError


# --- ScheduleTaskHandler ---


@dataclass
class ScheduleTaskPayload:
    prompt: str
    schedule_type: Literal["cron", "interval", "once"]
    schedule_value: str
    target_jid: str
    context_mode: Literal["group", "isolated"]


class ScheduleTaskHandler(IpcCommandHandler):
    command = "schedule_task"

    async def validate(self, data: dict[str, Any]) -> ScheduleTaskPayload:
        if not data.get("prompt") or not data.get("schedule_type") or not data.get("schedule_value") or not data.get("targetJid"):
            raise IpcHandlerError("Missing required fields", {"command": self.command})
        context_mode = data.get("context_mode", "isolated")
        if context_mode not in ("group", "isolated"):
            context_mode = "isolated"
        return ScheduleTaskPayload(
            prompt=data["prompt"],
            schedule_type=data["schedule_type"],
            schedule_value=data["schedule_value"],
            target_jid=data["targetJid"],
            context_mode=context_mode,
        )

    async def execute(self, payload: ScheduleTaskPayload, context: HandlerContext) -> None:
        registered_groups = context.deps.registered_groups()
        target_group = registered_groups.get(payload.target_jid)
        if not target_group:
            raise IpcHandlerError("Target group not registered", {"targetJid": payload.target_jid})

        target_folder = target_group.folder
        auth = AuthorizationPolicy(AuthContext(source_group=context.source_group, is_main=context.is_main))
        if not auth.can_schedule_task(target_folder):
            raise IpcHandlerError("Unauthorized schedule_task attempt", {"sourceGroup": context.source_group, "targetFolder": target_folder})

        try:
            task_id = context.deps.task_manager.create(
                group_folder=target_folder,
                chat_jid=payload.target_jid,
                prompt=payload.prompt,
                schedule_type=payload.schedule_type,
                schedule_value=payload.schedule_value,
                context_mode=payload.context_mode,
            )
            logger.info("Task created via IPC", task_id=task_id, source_group=context.source_group, target_folder=target_folder)
        except Exception as err:
            raise IpcHandlerError(str(err), {"scheduleType": payload.schedule_type, "scheduleValue": payload.schedule_value})


# --- PauseTaskHandler ---


class PauseTaskHandler(IpcCommandHandler):
    command = "pause_task"

    async def validate(self, data: dict[str, Any]) -> str:
        if not data.get("taskId"):
            raise IpcHandlerError("Missing taskId", {"command": self.command})
        return data["taskId"]

    async def execute(self, task_id: str, context: HandlerContext) -> None:
        try:
            context.deps.task_manager.get_authorized(task_id, context.source_group, context.is_main)
        except Exception as err:
            raise IpcHandlerError(str(err), {"taskId": task_id, "sourceGroup": context.source_group})
        context.deps.task_manager.pause(task_id)
        logger.info("Task paused via IPC", task_id=task_id, source_group=context.source_group)


# --- ResumeTaskHandler ---


class ResumeTaskHandler(IpcCommandHandler):
    command = "resume_task"

    async def validate(self, data: dict[str, Any]) -> str:
        if not data.get("taskId"):
            raise IpcHandlerError("Missing taskId", {"command": self.command})
        return data["taskId"]

    async def execute(self, task_id: str, context: HandlerContext) -> None:
        try:
            context.deps.task_manager.get_authorized(task_id, context.source_group, context.is_main)
        except Exception as err:
            raise IpcHandlerError(str(err), {"taskId": task_id, "sourceGroup": context.source_group})
        context.deps.task_manager.resume(task_id)
        logger.info("Task resumed via IPC", task_id=task_id, source_group=context.source_group)


# --- CancelTaskHandler ---


class CancelTaskHandler(IpcCommandHandler):
    command = "cancel_task"

    async def validate(self, data: dict[str, Any]) -> str:
        if not data.get("taskId"):
            raise IpcHandlerError("Missing taskId", {"command": self.command})
        return data["taskId"]

    async def execute(self, task_id: str, context: HandlerContext) -> None:
        try:
            context.deps.task_manager.get_authorized(task_id, context.source_group, context.is_main)
        except Exception as err:
            raise IpcHandlerError(str(err), {"taskId": task_id, "sourceGroup": context.source_group})
        context.deps.task_manager.cancel(task_id)
        logger.info("Task cancelled via IPC", task_id=task_id, source_group=context.source_group)
