"""Tests for container output parser."""

import json

from g2.execution.output_parser import ContainerOutputParser, OUTPUT_START_MARKER, OUTPUT_END_MARKER


class TestContainerOutputParser:
    def test_parses_valid_output(self):
        parser = ContainerOutputParser()
        assert parser.feed(OUTPUT_START_MARKER) is None
        assert parser.feed(json.dumps({"status": "success", "result": "Hello"})) is None
        output = parser.feed(OUTPUT_END_MARKER)
        assert output is not None
        assert output.status == "success"
        assert output.result == "Hello"

    def test_parses_error_output(self):
        parser = ContainerOutputParser()
        parser.feed(OUTPUT_START_MARKER)
        parser.feed(json.dumps({"status": "error", "error": "Something failed"}))
        output = parser.feed(OUTPUT_END_MARKER)
        assert output.status == "error"
        assert output.error == "Something failed"

    def test_extracts_session_id(self):
        parser = ContainerOutputParser()
        parser.feed(OUTPUT_START_MARKER)
        parser.feed(json.dumps({"status": "success", "result": "Done", "newSessionId": "sess-123"}))
        output = parser.feed(OUTPUT_END_MARKER)
        assert output.new_session_id == "sess-123"

    def test_ignores_lines_outside_markers(self):
        parser = ContainerOutputParser()
        assert parser.feed("random log line") is None
        assert parser.feed("another log line") is None

    def test_handles_invalid_json(self):
        parser = ContainerOutputParser()
        parser.feed(OUTPUT_START_MARKER)
        parser.feed("not valid json {{{")
        output = parser.feed(OUTPUT_END_MARKER)
        assert output.status == "error"
        assert "Failed to parse" in output.error

    def test_multiple_blocks(self):
        parser = ContainerOutputParser()

        parser.feed(OUTPUT_START_MARKER)
        parser.feed(json.dumps({"result": "First"}))
        out1 = parser.feed(OUTPUT_END_MARKER)

        parser.feed("some log between blocks")

        parser.feed(OUTPUT_START_MARKER)
        parser.feed(json.dumps({"result": "Second"}))
        out2 = parser.feed(OUTPUT_END_MARKER)

        assert out1.result == "First"
        assert out2.result == "Second"

    def test_multiline_json(self):
        parser = ContainerOutputParser()
        parser.feed(OUTPUT_START_MARKER)
        parser.feed('{"status": "success",')
        parser.feed('"result": "Hello"}')
        output = parser.feed(OUTPUT_END_MARKER)
        assert output.status == "success"
        assert output.result == "Hello"

    def test_strips_trailing_newlines(self):
        parser = ContainerOutputParser()
        assert parser.feed(OUTPUT_START_MARKER + "\n") is None
        parser.feed(json.dumps({"result": "ok"}) + "\r\n")
        output = parser.feed(OUTPUT_END_MARKER + "\n")
        assert output.result == "ok"

    def test_default_status_is_success(self):
        parser = ContainerOutputParser()
        parser.feed(OUTPUT_START_MARKER)
        parser.feed(json.dumps({"result": "Done"}))
        output = parser.feed(OUTPUT_END_MARKER)
        assert output.status == "success"
