"""Tests for message formatting."""

from g2.messaging.formatter import format_messages, strip_internal_tags, _xml_escape
from g2.messaging.types import NewMessage


def _msg(sender_name: str = "Alice", content: str = "Hello", **kwargs) -> NewMessage:
    return NewMessage(
        id="m1",
        chat_jid="group@g.us",
        sender="alice@s.whatsapp.net",
        sender_name=sender_name,
        content=content,
        timestamp="2024-01-01T00:00:00",
        **kwargs,
    )


class TestFormatMessages:
    def test_single_message(self):
        result = format_messages([_msg()])
        assert '<message sender="Alice">Hello</message>' == result

    def test_multiple_messages(self):
        msgs = [_msg(content="Hi"), _msg(sender_name="Bob", content="Hey")]
        result = format_messages(msgs)
        lines = result.split("\n")
        assert len(lines) == 2
        assert 'sender="Alice"' in lines[0]
        assert 'sender="Bob"' in lines[1]

    def test_xml_escaping_in_sender(self):
        result = format_messages([_msg(sender_name='Al"ice')])
        assert 'sender="Al&quot;ice"' in result

    def test_media_attributes(self):
        result = format_messages([_msg(media_type="image", media_mimetype="image/jpeg", media_path="/tmp/photo.jpg")])
        assert 'media_type="image"' in result
        assert 'media_mimetype="image/jpeg"' in result
        assert 'media_path="/tmp/photo.jpg"' in result

    def test_empty_list(self):
        assert format_messages([]) == ""


class TestStripInternalTags:
    def test_strips_internal_block(self):
        text = "Hello <internal>secret reasoning</internal> world"
        assert strip_internal_tags(text) == "Hello  world"

    def test_strips_multiline_internal(self):
        text = "Start\n<internal>\nline1\nline2\n</internal>\nEnd"
        assert strip_internal_tags(text) == "Start\n\nEnd"

    def test_no_internal_tags(self):
        assert strip_internal_tags("Hello world") == "Hello world"

    def test_empty_after_strip(self):
        assert strip_internal_tags("<internal>all hidden</internal>") == ""

    def test_multiple_internal_blocks(self):
        text = "A <internal>x</internal> B <internal>y</internal> C"
        assert strip_internal_tags(text) == "A  B  C"


class TestXmlEscape:
    def test_escapes_ampersand(self):
        assert _xml_escape("a&b") == "a&amp;b"

    def test_escapes_quotes(self):
        assert _xml_escape('a"b') == "a&quot;b"

    def test_escapes_angle_brackets(self):
        assert _xml_escape("a<b>c") == "a&lt;b&gt;c"

    def test_no_escaping_needed(self):
        assert _xml_escape("hello") == "hello"
