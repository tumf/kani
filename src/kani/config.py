"""Kani configuration models and loader.

Supports YAML config files with ${ENV_VAR} resolution and merging with defaults.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------


class ConfigNotFoundError(Exception):
    """Raised when no configuration file can be found."""

    def __init__(self, searched_paths: list[Path] | None = None) -> None:
        from kani.dirs import config_dir

        xdg_path = config_dir() / "config.yaml"
        paths_str = ""
        if searched_paths:
            paths_str = "\n".join(f"  - {p}" for p in searched_paths)

        msg = (
            "No kani configuration file found.\n"
            "\n"
            "Run `kani init` to create a starter config, or create one manually.\n"
        )
        if paths_str:
            msg += f"\nSearched:\n{paths_str}\n"
        msg += (
            f"\nDefault location: {xdg_path}\nOr set KANI_CONFIG=/path/to/config.yaml"
        )
        super().__init__(msg)
        self.searched_paths = searched_paths


class ConfigIncompleteError(Exception):
    """Raised when config exists but is missing required sections (e.g. profiles)."""

    def __init__(self, missing: str, config_path: Path | None = None) -> None:
        loc = f" ({config_path})" if config_path else ""
        msg = (
            f"Configuration{loc} is missing required section: {missing}\n"
            "\n"
            "Run `kani init` to generate a complete starter config,\n"
            "or add the missing section to your config file.\n"
            "See: https://github.com/tumf/kani#configuration"
        )
        super().__init__(msg)
        self.missing = missing
        self.config_path = config_path


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class ProviderConfig(BaseModel):
    """A backend LLM provider (OpenRouter, Anthropic, local proxy, etc.)."""

    name: str  # e.g. 'openrouter', 'cliproxy', 'anthropic'
    base_url: str  # e.g. 'https://openrouter.ai/api/v1'
    api_key: str = ""  # can reference env var with ${ENV_VAR}
    models: list[str] = Field(default_factory=list)  # optional model whitelist


class ModelEntry(BaseModel):
    """A model with optional provider override."""

    model: str
    provider: str = ""  # empty = inherit from tier or default


class TierModelConfig(BaseModel):
    """Model selection for a single complexity tier within a profile."""

    primary: str | ModelEntry  # model ID string OR {model, provider}
    fallback: list[str | ModelEntry] = Field(default_factory=list)
    provider: str = "default"  # tier-level default provider

    def resolve_primary(self) -> tuple[str, str]:
        """Return (model_id, provider_name). Provider may be empty string."""
        if isinstance(self.primary, ModelEntry):
            return self.primary.model, self.primary.provider
        return self.primary, ""

    def resolve_fallbacks(self) -> list[tuple[str, str]]:
        """Return list of (model_id, provider_name) tuples."""
        result: list[tuple[str, str]] = []
        for entry in self.fallback:
            if isinstance(entry, ModelEntry):
                result.append((entry.model, entry.provider))
            else:
                result.append((entry, ""))
        return result

    def primary_model_id(self) -> str:
        """Return just the model ID string (for backward compat)."""
        if isinstance(self.primary, ModelEntry):
            return self.primary.model
        return self.primary

    def fallback_model_ids(self) -> list[str]:
        """Return just the model ID strings (for backward compat)."""
        result: list[str] = []
        for entry in self.fallback:
            if isinstance(entry, ModelEntry):
                result.append(entry.model)
            else:
                result.append(entry)
        return result


class ProfileConfig(BaseModel):
    """A routing profile (auto, eco, premium, agentic)."""

    tiers: dict[str, TierModelConfig]  # SIMPLE, MEDIUM, COMPLEX, REASONING


class LLMClassifierConfig(BaseModel):
    """Configuration for the LLM-as-judge escalation classifier."""

    model: str = "google/gemini-2.5-flash-lite"
    base_url: str = "https://openrouter.ai/api/v1"
    api_key: str = ""


class SyncCompactionConfig(BaseModel):
    """Configuration for synchronous request-time context compaction."""

    enabled: bool = False
    threshold_percent: float = (
        80.0  # compact when prompt uses ≥ threshold_percent of context
    )
    protect_first_n: int = 1  # number of turns to protect at head
    protect_last_n: int = 2  # number of turns to protect at tail
    summary_model: str = (
        ""  # model to use for summarisation; empty = use compress profile
    )


class BackgroundPrecompactionConfig(BaseModel):
    """Configuration for background (async) precompaction."""

    enabled: bool = False
    trigger_percent: float = 70.0  # start background job when usage crosses this %
    max_concurrency: int = 2
    summary_ttl_seconds: int = 3600


class SessionConfig(BaseModel):
    """Configuration for session identity resolution."""

    header_name: str = "X-Kani-Session-Id"


class ContextCompactionConfig(BaseModel):
    """Smart-proxy context compaction sub-configuration."""

    enabled: bool = False
    sync_compaction: SyncCompactionConfig = Field(default_factory=SyncCompactionConfig)
    background_precompaction: BackgroundPrecompactionConfig = Field(
        default_factory=BackgroundPrecompactionConfig
    )
    session: SessionConfig = Field(default_factory=SessionConfig)
    context_window_tokens: int = (
        128000  # assumed context window for threshold calculation
    )


class SmartProxyConfig(BaseModel):
    """Smart-proxy feature configuration."""

    context_compaction: ContextCompactionConfig = Field(
        default_factory=ContextCompactionConfig
    )


class KaniConfig(BaseModel):
    """Top-level Kani configuration."""

    host: str = "0.0.0.0"
    port: int = 18420
    providers: dict[str, ProviderConfig] = Field(default_factory=dict)
    default_provider: str = "openrouter"
    profiles: dict[str, ProfileConfig] = Field(default_factory=dict)
    default_profile: str = "auto"
    llm_classifier: LLMClassifierConfig | None = None
    smart_proxy: SmartProxyConfig = Field(default_factory=SmartProxyConfig)


# ---------------------------------------------------------------------------
# Env-var resolution
# ---------------------------------------------------------------------------

_ENV_RE = re.compile(r"\$\{([^}]+)\}")


def resolve_env(value: str) -> str:
    """Replace ${VAR} placeholders with environment variable values."""

    def _replace(m: re.Match) -> str:
        var = m.group(1)
        return os.environ.get(var, "")

    return _ENV_RE.sub(_replace, value)


def resolve_env_recursive(obj: Any) -> Any:
    """Walk a data structure and resolve all ${VAR} strings."""
    if isinstance(obj, str):
        return resolve_env(obj)
    if isinstance(obj, dict):
        return {k: resolve_env_recursive(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [resolve_env_recursive(v) for v in obj]
    return obj


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------


def _default_config_paths() -> list[Path]:
    """Return ordered list of config file search paths.

    Priority: ./config.yaml → $XDG_CONFIG_HOME/kani/config.yaml → /etc/kani/config.yaml
    """
    from kani.dirs import config_dir

    return [
        Path("config.yaml"),
        Path("config.yml"),
        config_dir() / "config.yaml",
        Path("/etc/kani/config.yaml"),
    ]


def _find_config_file(explicit_path: str | Path | None = None) -> Path | None:
    """Locate a config file, checking explicit path then defaults."""
    if explicit_path is not None:
        p = Path(explicit_path).expanduser()
        return p if p.is_file() else None

    # Check env var
    env_path = os.environ.get("KANI_CONFIG")
    if env_path:
        p = Path(env_path).expanduser()
        if p.is_file():
            return p

    # Search default locations (XDG-aware)
    for candidate in _default_config_paths():
        if candidate.is_file():
            return candidate

    return None


def load_config(
    path: str | Path | None = None,
    *,
    overrides: dict[str, Any] | None = None,
    strict: bool = False,
) -> KaniConfig:
    """Load KaniConfig from a YAML file with env-var resolution.

    Args:
        path: Explicit path to config YAML, or None to auto-discover.
        overrides: Dict of overrides merged on top of file config.
        strict: If True, raise ConfigNotFoundError / ConfigIncompleteError
                when the config is missing or incomplete. Default False
                preserves backward compatibility (returns empty defaults).

    Returns:
        Fully resolved KaniConfig instance.
    """
    raw: dict[str, Any] = {}

    config_file = _find_config_file(path)

    if config_file is not None:
        with open(config_file) as f:
            loaded = yaml.safe_load(f)
            if isinstance(loaded, dict):
                raw = loaded
    elif strict:
        # Explicit path given but not found
        if path is not None:
            raise ConfigNotFoundError([Path(path).expanduser()])
        # Auto-discovery failed
        raise ConfigNotFoundError(_default_config_paths())

    # Merge overrides
    if overrides:
        raw = _deep_merge(raw, overrides)

    # Resolve env vars in raw data
    raw = resolve_env_recursive(raw)

    cfg = KaniConfig.model_validate(raw)

    if strict and not cfg.profiles:
        raise ConfigIncompleteError("profiles", config_file)

    return cfg


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge *override* into *base* (override wins)."""
    result = dict(base)
    for key, val in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = _deep_merge(result[key], val)
        else:
            result[key] = val
    return result
