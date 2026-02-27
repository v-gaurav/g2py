"""File operations (rename, delete, move) for skill application."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from .types import FileOperation, FileOpsResult

if TYPE_CHECKING:
    from pathlib import Path


def _safe_path(project_root: Path, relative_path: str) -> Path | None:
    """Resolve a relative path within the project root, rejecting escapes."""
    resolved = (project_root / relative_path).resolve()
    root_resolved = project_root.resolve()
    if resolved != root_resolved and not str(resolved).startswith(str(root_resolved) + os.sep):
        return None
    return resolved


def execute_file_ops(ops: list[FileOperation], project_root: Path) -> FileOpsResult:
    """Execute a list of file operations within the project root.

    Returns a FileOpsResult describing what was executed and any errors.
    On the first error, execution stops and the result is returned.
    """
    result = FileOpsResult(
        success=True,
        executed=[],
        warnings=[],
        errors=[],
    )

    root = project_root.resolve()

    for op in ops:
        if op.type == "rename":
            if not op.from_ or not op.to:
                result.errors.append("rename: requires 'from' and 'to'")
                result.success = False
                return result
            from_path = _safe_path(root, op.from_)
            to_path = _safe_path(root, op.to)
            if not from_path:
                result.errors.append(f"rename: path escapes project root: {op.from_}")
                result.success = False
                return result
            if not to_path:
                result.errors.append(f"rename: path escapes project root: {op.to}")
                result.success = False
                return result
            if not from_path.exists():
                result.errors.append(f"rename: source does not exist: {op.from_}")
                result.success = False
                return result
            if to_path.exists():
                result.errors.append(f"rename: target already exists: {op.to}")
                result.success = False
                return result
            from_path.rename(to_path)
            result.executed.append(op)

        elif op.type == "delete":
            if not op.path:
                result.errors.append("delete: requires 'path'")
                result.success = False
                return result
            del_path = _safe_path(root, op.path)
            if not del_path:
                result.errors.append(f"delete: path escapes project root: {op.path}")
                result.success = False
                return result
            if not del_path.exists():
                result.warnings.append(f"delete: file does not exist (skipped): {op.path}")
                result.executed.append(op)
                continue
            del_path.unlink()
            result.executed.append(op)

        elif op.type == "move":
            if not op.from_ or not op.to:
                result.errors.append("move: requires 'from' and 'to'")
                result.success = False
                return result
            src_path = _safe_path(root, op.from_)
            dst_path = _safe_path(root, op.to)
            if not src_path:
                result.errors.append(f"move: path escapes project root: {op.from_}")
                result.success = False
                return result
            if not dst_path:
                result.errors.append(f"move: path escapes project root: {op.to}")
                result.success = False
                return result
            if not src_path.exists():
                result.errors.append(f"move: source does not exist: {op.from_}")
                result.success = False
                return result
            if dst_path.exists():
                result.errors.append(f"move: target already exists: {op.to}")
                result.success = False
                return result
            dst_path.parent.mkdir(parents=True, exist_ok=True)
            src_path.rename(dst_path)
            result.executed.append(op)

        else:
            result.errors.append(f"unknown operation type: {op.type}")
            result.success = False
            return result

    return result
