"""Session IPC handlers: clear, resume, search, archive."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from g2.groups.paths import GroupPaths
from g2.infrastructure.logger import logger
from g2.ipc.dispatcher import HandlerContext, IpcCommandHandler, IpcHandlerError


# --- ClearSessionHandler ---


class ClearSessionHandler(IpcCommandHandler):
    command = "clear_session"

    async def validate(self, data: dict[str, Any]) -> str | None:
        return data.get("name")

    async def execute(self, name: str | None, context: HandlerContext) -> None:
        context.deps.session_manager.clear(context.source_group, name)

        groups = context.deps.registered_groups()
        for jid, g in groups.items():
            if g.folder == context.source_group:
                context.deps.close_stdin(jid)
                break

        logger.info("Session cleared via IPC", source_group=context.source_group)


# --- ResumeSessionHandler ---


@dataclass
class ResumeSessionPayload:
    session_history_id: str
    save_name: str | None


class ResumeSessionHandler(IpcCommandHandler):
    command = "resume_session"

    async def validate(self, data: dict[str, Any]) -> ResumeSessionPayload:
        if not data.get("sessionHistoryId"):
            raise IpcHandlerError("Missing sessionHistoryId", {"command": self.command})
        return ResumeSessionPayload(
            session_history_id=data["sessionHistoryId"],
            save_name=data.get("saveName"),
        )

    async def execute(self, payload: ResumeSessionPayload, context: HandlerContext) -> None:
        try:
            restored_session_id = context.deps.session_manager.resume(
                context.source_group,
                int(payload.session_history_id),
                payload.save_name,
            )
        except (ValueError, Exception):
            raise IpcHandlerError(
                "Conversation archive entry not found",
                {"sourceGroup": context.source_group, "id": payload.session_history_id},
            )

        groups = context.deps.registered_groups()
        for jid, g in groups.items():
            if g.folder == context.source_group:
                context.deps.close_stdin(jid)
                break

        logger.info("Session resumed via IPC", source_group=context.source_group, restored_session_id=restored_session_id)


# --- SearchSessionsHandler ---


@dataclass
class SearchSessionsPayload:
    query: str
    request_id: str


class SearchSessionsHandler(IpcCommandHandler):
    command = "search_sessions"

    async def validate(self, data: dict[str, Any]) -> SearchSessionsPayload:
        if not data.get("requestId"):
            raise IpcHandlerError("Missing requestId", {"command": self.command})
        return SearchSessionsPayload(query=data.get("query", ""), request_id=data["requestId"])

    async def execute(self, payload: SearchSessionsPayload, context: HandlerContext) -> None:
        results = context.deps.session_manager.search(context.source_group, payload.query)

        responses_dir = GroupPaths.ipc_responses_dir(context.source_group)
        responses_dir.mkdir(parents=True, exist_ok=True)

        response_path = responses_dir / f"{payload.request_id}.json"
        tmp_path = response_path.with_suffix(".json.tmp")
        tmp_path.write_text(json.dumps(results))
        tmp_path.rename(response_path)

        logger.info(
            "Search sessions completed",
            source_group=context.source_group,
            query=payload.query,
            result_count=len(results),
        )


# --- ArchiveSessionHandler ---


@dataclass
class ArchiveSessionPayload:
    session_id: str
    name: str
    content: str
    timestamp: str


class ArchiveSessionHandler(IpcCommandHandler):
    command = "archive_session"

    async def validate(self, data: dict[str, Any]) -> ArchiveSessionPayload:
        if not data.get("sessionId") or not data.get("name"):
            raise IpcHandlerError("Missing sessionId or name", {"command": self.command})
        return ArchiveSessionPayload(
            session_id=data["sessionId"],
            name=data["name"],
            content=data.get("content", ""),
            timestamp=data.get("timestamp", ""),
        )

    async def execute(self, payload: ArchiveSessionPayload, context: HandlerContext) -> None:
        context.deps.session_manager.archive(
            context.source_group,
            payload.session_id,
            payload.name,
            payload.content,
        )
        logger.info(
            "Session archived via IPC",
            source_group=context.source_group,
            session_id=payload.session_id,
            name=payload.name,
        )
