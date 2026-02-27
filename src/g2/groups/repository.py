"""Registered group persistence."""

from __future__ import annotations

import json
import sqlite3

from g2.groups.types import ContainerConfig, RegisteredGroup


def _safe_parse(raw: str) -> dict | None:
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


class GroupRepository:
    def __init__(self, db: sqlite3.Connection) -> None:
        self._db = db

    def get_registered_group(self, jid: str) -> RegisteredGroup | None:
        row = self._db.execute("SELECT * FROM registered_groups WHERE jid = ?", (jid,)).fetchone()
        if not row:
            return None
        return self._row_to_group(row)

    def set_registered_group(self, jid: str, group: RegisteredGroup | dict) -> None:
        if isinstance(group, dict):
            # Support dict input for migrations
            g = group
            self._db.execute(
                """INSERT OR REPLACE INTO registered_groups
                   (jid, name, folder, trigger_pattern, added_at, container_config, requires_trigger, channel)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    jid,
                    g.get("name", ""),
                    g.get("folder", ""),
                    g.get("trigger", ""),
                    g.get("added_at", ""),
                    json.dumps(g["containerConfig"]) if g.get("containerConfig") else None,
                    1 if g.get("requiresTrigger", True) else 0,
                    g.get("channel", "whatsapp"),
                ),
            )
        else:
            self._db.execute(
                """INSERT OR REPLACE INTO registered_groups
                   (jid, name, folder, trigger_pattern, added_at, container_config, requires_trigger, channel)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    jid,
                    group.name,
                    group.folder,
                    group.trigger,
                    group.added_at,
                    group.container_config.model_dump_json() if group.container_config else None,
                    1 if group.requires_trigger is None or group.requires_trigger else 0,
                    group.channel or "whatsapp",
                ),
            )
        self._db.commit()

    def get_all_registered_groups(self) -> dict[str, RegisteredGroup]:
        rows = self._db.execute("SELECT * FROM registered_groups").fetchall()
        result: dict[str, RegisteredGroup] = {}
        for row in rows:
            jid = row["jid"]
            result[jid] = self._row_to_group(row)
        return result

    def _row_to_group(self, row: sqlite3.Row) -> RegisteredGroup:
        container_config = None
        if row["container_config"]:
            parsed = _safe_parse(row["container_config"])
            if parsed:
                container_config = ContainerConfig(**parsed)

        requires_trigger: bool | None = None
        rt_val = row["requires_trigger"]
        if rt_val is not None:
            requires_trigger = rt_val == 1

        return RegisteredGroup(
            name=row["name"],
            folder=row["folder"],
            trigger=row["trigger_pattern"],
            added_at=row["added_at"],
            channel=row["channel"] or "whatsapp",
            container_config=container_config,
            requires_trigger=requires_trigger,
        )
