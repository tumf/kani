"""Tests for kani keys CLI commands."""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from kani.cli import main


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture(autouse=True)
def isolate_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("KANI_DATA_DIR", str(tmp_path))


class TestKeysAdd:
    def test_add_shows_key(self, runner):
        result = runner.invoke(main, ["keys", "add", "myservice"])
        assert result.exit_code == 0
        assert "Created API key: myservice" in result.output
        assert "kani-" in result.output
        assert "cannot be shown again" in result.output

    def test_add_multiple(self, runner):
        runner.invoke(main, ["keys", "add", "svc1"])
        runner.invoke(main, ["keys", "add", "svc2"])
        result = runner.invoke(main, ["keys", "list"])
        assert "svc1" in result.output
        assert "svc2" in result.output


class TestKeysList:
    def test_list_empty(self, runner):
        result = runner.invoke(main, ["keys", "list"])
        assert result.exit_code == 0
        assert "No API keys configured" in result.output

    def test_list_shows_entries(self, runner):
        runner.invoke(main, ["keys", "add", "prod"])
        result = runner.invoke(main, ["keys", "list"])
        assert result.exit_code == 0
        assert "prod" in result.output
        assert "NAME" in result.output


class TestKeysRemove:
    def test_remove_by_name(self, runner):
        runner.invoke(main, ["keys", "add", "deleteme"])
        result = runner.invoke(main, ["keys", "remove", "deleteme"])
        assert result.exit_code == 0
        assert "Removed" in result.output

        result = runner.invoke(main, ["keys", "list"])
        assert "No API keys configured" in result.output

    def test_remove_nonexistent(self, runner):
        result = runner.invoke(main, ["keys", "remove", "ghost"])
        assert result.exit_code != 0
        assert "No API key found" in result.output
