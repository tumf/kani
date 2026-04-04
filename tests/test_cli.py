"""Tests for kani CLI — config error handling and init command."""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from kani.cli import main
from kani.config import (
    ConfigIncompleteError,
    ConfigNotFoundError,
    FeatureAnnotatorConfig,
    LLMClassifierConfig,
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
        result = runner.invoke(main, ["route", "hello", "--config", str(config_path)])
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

    def test_tier_fallback_null_normalized_to_empty_list(self, empty_dir):
        config_path = empty_dir / "config.yaml"
        config_path.write_text(
            """
default_provider: openrouter
providers:
  openrouter:
    name: openrouter
    base_url: https://openrouter.ai/api/v1
profiles:
  auto:
    tiers:
      SIMPLE:
        primary: model-a
        fallback: null
"""
        )
        cfg = load_config(str(config_path), strict=True)
        assert cfg.profiles["auto"].tiers["SIMPLE"].fallback == []


class TestAuxLLMProviderConfig:
    def test_llm_classifier_rejects_deprecated_connection_fields(self) -> None:
        with pytest.raises(ValueError):
            LLMClassifierConfig.model_validate(
                {
                    "model": "gpt-4o-mini",
                    "base_url": "https://openrouter.ai/api/v1",
                }
            )

    def test_feature_annotator_rejects_deprecated_connection_fields(self) -> None:
        with pytest.raises(ValueError):
            FeatureAnnotatorConfig.model_validate(
                {
                    "model": "gpt-4o-mini",
                    "api_key": "dummy",
                }
            )

    def test_aux_llm_provider_resolution_and_default_fallback(
        self, empty_dir, monkeypatch
    ) -> None:
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        config_path = empty_dir / "config.yaml"
        config_path.write_text(
            """
default_provider: openrouter
providers:
  openrouter:
    name: openrouter
    base_url: https://openrouter.ai/api/v1
    api_key: ${OPENROUTER_API_KEY}
  local:
    name: local
    base_url: http://127.0.0.1:8317/v1
    api_key: local-key
profiles:
  auto:
    tiers:
      SIMPLE:
        primary: gpt-4o-mini
llm_classifier:
  model: gpt-4o-mini
feature_annotator:
  model: gpt-4o-mini
  provider: local
"""
        )

        cfg = load_config(str(config_path), strict=True)

        llm_base_url, llm_api_key = cfg.llm_classifier_resolved() or ("", "")
        annotator_base_url, annotator_api_key = cfg.feature_annotator_resolved() or (
            "",
            "",
        )

        assert llm_base_url == "https://openrouter.ai/api/v1"
        assert llm_api_key == ""
        assert annotator_base_url == "http://127.0.0.1:8317/v1"
        assert annotator_api_key == "local-key"

    def test_aux_llm_resolution_fails_for_unknown_provider(self, empty_dir) -> None:
        config_path = empty_dir / "config.yaml"
        config_path.write_text(
            """
default_provider: openrouter
providers:
  openrouter:
    name: openrouter
    base_url: https://openrouter.ai/api/v1
profiles:
  auto:
    tiers:
      SIMPLE:
        primary: gpt-4o-mini
feature_annotator:
  model: gpt-4o-mini
  provider: unknown
"""
        )

        with pytest.raises(ValueError, match="Unknown provider"):
            load_config(str(config_path), strict=True)


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
