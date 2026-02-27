"""Tests for configuration."""

import os
import tempfile
from pathlib import Path

from g2.infrastructure.config import read_env_file, TimeoutConfig


class TestReadEnvFile:
    def test_reads_env_values(self, tmp_path, monkeypatch):
        env_file = tmp_path / ".env"
        env_file.write_text("KEY1=value1\nKEY2=value2\n")
        monkeypatch.chdir(tmp_path)

        result = read_env_file(["KEY1", "KEY2"])
        assert result == {"KEY1": "value1", "KEY2": "value2"}

    def test_strips_quotes(self, tmp_path, monkeypatch):
        env_file = tmp_path / ".env"
        env_file.write_text('KEY1="quoted"\nKEY2=\'single\'\n')
        monkeypatch.chdir(tmp_path)

        result = read_env_file(["KEY1", "KEY2"])
        assert result["KEY1"] == "quoted"
        assert result["KEY2"] == "single"

    def test_skips_comments(self, tmp_path, monkeypatch):
        env_file = tmp_path / ".env"
        env_file.write_text("# comment\nKEY1=value1\n")
        monkeypatch.chdir(tmp_path)

        result = read_env_file(["KEY1"])
        assert result == {"KEY1": "value1"}

    def test_skips_empty_lines(self, tmp_path, monkeypatch):
        env_file = tmp_path / ".env"
        env_file.write_text("\n\nKEY1=value1\n\n")
        monkeypatch.chdir(tmp_path)

        result = read_env_file(["KEY1"])
        assert result == {"KEY1": "value1"}

    def test_only_requested_keys(self, tmp_path, monkeypatch):
        env_file = tmp_path / ".env"
        env_file.write_text("KEY1=value1\nKEY2=value2\n")
        monkeypatch.chdir(tmp_path)

        result = read_env_file(["KEY1"])
        assert "KEY2" not in result

    def test_missing_file_returns_empty(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = read_env_file(["KEY1"])
        assert result == {}

    def test_empty_values_skipped(self, tmp_path, monkeypatch):
        env_file = tmp_path / ".env"
        env_file.write_text("KEY1=\n")
        monkeypatch.chdir(tmp_path)

        result = read_env_file(["KEY1"])
        assert "KEY1" not in result


class TestTimeoutConfig:
    def test_defaults(self):
        config = TimeoutConfig()
        assert config.container_timeout > 0
        assert config.idle_timeout > 0

    def test_hard_timeout_at_least_idle_plus_buffer(self):
        config = TimeoutConfig(container_timeout=60000, idle_timeout=60000)
        assert config.get_hard_timeout() >= config.idle_timeout + 30000

    def test_hard_timeout_at_least_container_timeout(self):
        config = TimeoutConfig(container_timeout=3600000, idle_timeout=60000)
        assert config.get_hard_timeout() >= config.container_timeout

    def test_custom_values(self):
        config = TimeoutConfig(container_timeout=5000, idle_timeout=10000)
        assert config.container_timeout == 5000
        assert config.idle_timeout == 10000
