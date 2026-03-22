"""Tests for kani CLI — config error handling and init command."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest
from click.testing import CliRunner

from kani.cli import main
from kani.config import (
    ConfigIncompleteError,
    ConfigNotFoundError,
    load_config,
)


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def empty_dir(tmp_path, monkeypatch):
    """Run in a temp dir with no config files and unset KANI_CONFIG."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("KANI_CONFIG", raising=False)
    # Also override XDG so it doesn't find real user config
    monkeypatch.setenv("KANI_CONFIG_DIR", str(tmp_path / "xdg_config"))
    return tmp_path


class TestConfigErrors:
    """Config error UX — no stack traces for missing config."""

    def test_route_no_config_shows_friendly_error(self, runner, empty_dir):
        result = runner.invoke(main, ["route", "hello world"])
        assert result.exit_code != 0
        assert "No kani configuration file found" in result.output
        assert "kani init" in result.output
        # Must NOT show a Python traceback
        assert "Traceback" not in result.output

    def test_serve_no_config_shows_friendly_error(self, runner, empty_dir):
        result = runner.invoke(main, ["serve"])
        assert result.exit_code != 0
        assert "No kani configuration file found" in result.output

    def test_config_no_config_shows_friendly_error(self, runner, empty_dir):
        result = runner.invoke(main, ["config"])
        assert result.exit_code != 0
        assert "No kani configuration file found" in result.output

    def test_route_empty_config_shows_friendly_error(self, runner, empty_dir):
        # Config file exists but has no profiles
        config_path = empty_dir / "config.yaml"
        config_path.write_text("host: 0.0.0.0\nport: 18420\n")
        monkeypatch_env = os.environ.copy()
        result = runner.invoke(
            main, ["route", "hello", "--config", str(config_path)]
        )
        assert result.exit_code != 0
        assert "missing required section" in result.output
        assert "profiles" in result.output
        assert "Traceback" not in result.output


class TestConfigExceptions:
    """Direct exception tests."""

    def test_config_not_found_strict(self, empty_dir):
        with pytest.raises(ConfigNotFoundError) as exc_info:
            load_config(strict=True)
        msg = str(exc_info.value)
        assert "kani init" in msg

    def test_config_not_found_explicit_path(self, empty_dir):
        with pytest.raises(ConfigNotFoundError):
            load_config("/nonexistent/path.yaml", strict=True)

    def test_config_incomplete_no_profiles(self, empty_dir):
        config_path = empty_dir / "config.yaml"
        config_path.write_text("host: 0.0.0.0\n")
        with pytest.raises(ConfigIncompleteError) as exc_info:
            load_config(str(config_path), strict=True)
        assert "profiles" in str(exc_info.value)

    def test_non_strict_returns_defaults(self, empty_dir):
        """Non-strict mode (default) still works for backward compat."""
        cfg = load_config()
        assert cfg.host == "0.0.0.0"
        assert cfg.profiles == {}


class TestInitCommand:
    """kani init command."""

    def test_init_creates_config(self, runner, empty_dir):
        xdg_dir = empty_dir / "xdg_config"
        result = runner.invoke(main, ["init"])
        assert result.exit_code == 0
        assert "Created starter config" in result.output
        config_file = xdg_dir / "config.yaml"
        assert config_file.exists()
        content = config_file.read_text()
        assert "profiles:" in content
        assert "auto:" in content

    def test_init_custom_path(self, runner, empty_dir):
        target = empty_dir / "my_config.yaml"
        result = runner.invoke(main, ["init", "--path", str(target)])
        assert result.exit_code == 0
        assert target.exists()

    def test_init_refuses_overwrite(self, runner, empty_dir):
        xdg_dir = empty_dir / "xdg_config"
        xdg_dir.mkdir(parents=True, exist_ok=True)
        (xdg_dir / "config.yaml").write_text("existing")
        result = runner.invoke(main, ["init"])
        assert result.exit_code != 0
        assert "already exists" in result.output

    def test_init_force_overwrites(self, runner, empty_dir):
        xdg_dir = empty_dir / "xdg_config"
        xdg_dir.mkdir(parents=True, exist_ok=True)
        (xdg_dir / "config.yaml").write_text("existing")
        result = runner.invoke(main, ["init", "--force"])
        assert result.exit_code == 0
        content = (xdg_dir / "config.yaml").read_text()
        assert "profiles:" in content

    def test_init_then_route_works(self, runner, empty_dir):
        """After init, route should work (with heuristic scorer)."""
        result = runner.invoke(main, ["init"])
        assert result.exit_code == 0
        # Now route should find the config via XDG
        result = runner.invoke(main, ["route", "hello"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "model" in data
        assert "tier" in data


# Need json import for the last test
import json
