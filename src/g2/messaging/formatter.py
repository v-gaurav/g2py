"""Message formatting transforms."""

from __future__ import annotations

import re

from g2.messaging.types import NewMessage


def format_messages(messages: list[NewMessage]) -> str:
    """Format a list of messages into a single prompt string.

    Each message is wrapped in XML-like tags with metadata attributes.
    """
    parts: list[str] = []
    for msg in messages:
        name = _xml_escape(msg.sender_name)
        content = msg.content

        # Build media description if present
        media_desc = ""
        if msg.media_type:
            media_desc = f' media_type="{msg.media_type}"'
            if msg.media_mimetype:
                media_desc += f' media_mimetype="{msg.media_mimetype}"'
            if msg.media_path:
                media_desc += f' media_path="{msg.media_path}"'

        parts.append(f'<message sender="{name}"{media_desc}>{content}</message>')

    return "\n".join(parts)


def strip_internal_tags(text: str) -> str:
    """Strip <internal>...</internal> blocks from agent output."""
    return re.sub(r"<internal>[\s\S]*?</internal>", "", text).strip()


def _xml_escape(s: str) -> str:
    """Escape special XML characters in attribute values."""
    return s.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;").replace(">", "&gt;")
