"""Path remapping for skills that relocate files."""

from __future__ import annotations

from .state import read_state, write_state


def resolve_path_remap(rel_path: str, remap: dict[str, str]) -> str:
    """Resolve a relative path through the remap table."""
    return remap.get(rel_path, rel_path)


def load_path_remap() -> dict[str, str]:
    """Load the current path remap from state."""
    state = read_state()
    return state.path_remap or {}


def record_path_remap(remap: dict[str, str]) -> None:
    """Merge new path remappings into state."""
    state = read_state()
    state.path_remap = {**(state.path_remap or {}), **remap}
    write_state(state)
