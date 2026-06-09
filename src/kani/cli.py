"""kani CLI — serve, route, and inspect configuration."""

from __future__ import annotations

import json
import os
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn

import click
import yaml

from kani.config import ConfigIncompleteError, ConfigNotFoundError


@dataclass(frozen=True)
class DoctorResult:
    """One human-readable diagnostic finding."""

    severity: str
    title: str
    message: str

    def format_line(self) -> str:
        """Return a concise line with sensitive values redacted defensively."""
        return f"[{self.severity.upper()}] {self.title}: {_redact_secret_text(self.message)}"


_SECRET_MARKERS = ("api_key", "apikey", "authorization", "bearer", "token", "secret")


def _redact_secret_text(value: str) -> str:
    """Best-effort redaction for accidental secret-like substrings in diagnostics."""
    redacted_words: list[str] = []
    for word in value.split():
        lowered = word.lower()
        if word.startswith(("sk-", "kani_")) or any(
            marker in lowered for marker in _SECRET_MARKERS
        ):
            redacted_words.append("***")
        else:
            redacted_words.append(word)
    return " ".join(redacted_words)


def _runtime_loads_classifier_asset(asset_name: str) -> bool:
    """Return whether scorer.py contains explicit runtime loading for an asset."""
    scorer_path = Path(__file__).with_name("scorer.py")
    source = scorer_path.read_text()
    return asset_name in source and any(
        marker in source for marker in ("pickle.load", "joblib.load", "load_model")
    )


def _classifier_asset_result(asset_name: str, models_dir: Path) -> DoctorResult:
    asset_path = models_dir / asset_name
    if not asset_path.exists():
        return DoctorResult(
            "info",
            asset_name,
            f"not found at {asset_path}; current runtime uses heuristic scorer",
        )

    if _runtime_loads_classifier_asset(asset_name):
        return DoctorResult(
            "ok",
            asset_name,
            "present and explicit runtime loading evidence was found in scorer.py",
        )

    if asset_name == "tier_classifier.pkl":
        status = "present but legacy/unused by current runtime routing"
    else:
        status = "present but not loaded by current runtime routing"
    return DoctorResult("warn", asset_name, status)


def _profile_tier_count(profile: object) -> int:
    tiers = getattr(profile, "tiers", {})
    return len(tiers) if isinstance(tiers, dict) else 0


def _load_raw_config_keys(config_path: str | None) -> set[str]:
    """Return top-level YAML keys before KaniConfig normalizes legacy aliases."""
    if config_path is None:
        return set()

    raw_path = Path(config_path).expanduser()
    if not raw_path.exists():
        return set()

    with raw_path.open() as f:
        loaded = yaml.safe_load(f)

    if not isinstance(loaded, dict):
        return set()
    return {str(key) for key in loaded}


def _model_metadata_result(cfg: object, raw_config_keys: set[str]) -> DoctorResult:
    has_raw_model_rules = "model_rules" in raw_config_keys
    has_raw_model_capabilities = "model_capabilities" in raw_config_keys
    model_rules = getattr(cfg, "model_rules", [])

    if has_raw_model_rules and has_raw_model_capabilities:
        return DoctorResult(
            "error",
            "model metadata",
            "both model_rules and legacy model_capabilities are configured",
        )

    if has_raw_model_capabilities:
        return DoctorResult(
            "warn",
            "model metadata",
            f"legacy model_capabilities normalized to {len(model_rules)} model_rules",
        )

    return DoctorResult(
        "ok",
        "model metadata",
        f"model_rules entries: {len(model_rules)}; legacy model_capabilities entries: 0",
    )


def build_doctor_results(
    config_path: str | None, *, models_dir: Path | None = None
) -> list[DoctorResult]:
    """Build read-only diagnostics for config and bundled classifier assets."""
    from kani.config import load_config

    raw_config_keys = _load_raw_config_keys(config_path)
    cfg = load_config(config_path, strict=True)
    resolved_models_dir = models_dir or Path.cwd() / "models"

    results = [
        DoctorResult("ok", "config", "strict config loaded successfully"),
        DoctorResult(
            "ok" if cfg.providers else "error",
            "providers",
            f"{len(cfg.providers)} provider(s) configured: {', '.join(cfg.providers) or '(none)'}",
        ),
        DoctorResult(
            "ok" if cfg.profiles else "error",
            "profiles",
            "; ".join(
                f"{name} ({_profile_tier_count(profile)} tier(s))"
                for name, profile in cfg.profiles.items()
            )
            or "(none)",
        ),
    ]

    results.append(_model_metadata_result(cfg, raw_config_keys))

    results.append(_classifier_asset_result("tier_classifier.pkl", resolved_models_dir))
    results.append(
        _classifier_asset_result("feature_classifier.pkl", resolved_models_dir)
    )
    return results


def _handle_config_error(e: ConfigNotFoundError | ConfigIncompleteError) -> NoReturn:
    """Print a user-friendly config error and exit."""
    click.echo(f"Error: {e}", err=True)
    raise SystemExit(1)


@click.group()
@click.version_option(package_name="kani")
def main():
    """kani — LLM smart router with OpenAI-compatible proxy."""


@main.command()
@click.option("--config", "config_path", default=None, help="Path to config.yaml")
@click.option("--host", default=None, help="Bind host (overrides config)")
@click.option("--port", default=None, type=int, help="Bind port (overrides config)")
def serve(config_path: str | None, host: str | None, port: int | None):
    """Start the kani proxy server."""
    import uvicorn

    from kani.config import load_config
    from kani.proxy import app, configure

    try:
        cfg = load_config(config_path, strict=True)
    except (ConfigNotFoundError, ConfigIncompleteError) as e:
        _handle_config_error(e)

    configure(config_path)

    bind_host = host or cfg.host
    bind_port = port or cfg.port

    click.echo(f"Starting kani proxy on {bind_host}:{bind_port}")

    uvicorn.run(app, host=bind_host, port=bind_port, log_level="info")


@main.command("route")
@click.argument("prompt")
@click.option("--config", "config_path", default=None, help="Path to config.yaml")
@click.option(
    "--profile", default=None, help="Routing profile (e.g. auto, eco, premium)"
)
def route_cmd(prompt: str, config_path: str | None, profile: str | None):
    """Classify a prompt and show the routing decision."""
    from kani.config import load_config
    from kani.router import Router

    try:
        cfg = load_config(config_path, strict=True)
    except (ConfigNotFoundError, ConfigIncompleteError) as e:
        _handle_config_error(e)

    router = Router(cfg)

    messages = [{"role": "user", "content": prompt}]
    decision = router.route(messages, profile=profile)

    click.echo(json.dumps(decision.model_dump(), indent=2))


@main.command("doctor")
@click.option("--config", "config_path", default=None, help="Path to config.yaml")
@click.option(
    "--models-dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help="Directory containing classifier assets (default: ./models)",
)
def doctor_cmd(config_path: str | None, models_dir: Path | None):
    """Run read-only diagnostics for config and classifier assets."""
    click.echo("kani doctor")
    click.echo("===========")
    try:
        results = build_doctor_results(config_path, models_dir=models_dir)
    except (ConfigNotFoundError, ConfigIncompleteError, ValueError) as e:
        click.echo(
            f"[ERROR] config: {_redact_secret_text(type(e).__name__ + ': ' + str(e))}"
        )
        raise SystemExit(1) from None

    for result in results:
        click.echo(result.format_line())

    if any(result.severity == "error" for result in results):
        raise SystemExit(1)


@main.command("config")
@click.option("--config", "config_path", default=None, help="Path to config.yaml")
def config_cmd(config_path: str | None):
    """Show current configuration."""
    from kani.config import load_config

    try:
        cfg = load_config(config_path, strict=True)
    except (ConfigNotFoundError, ConfigIncompleteError) as e:
        _handle_config_error(e)

    click.echo(f"Host: {cfg.host}")
    click.echo(f"Port: {cfg.port}")
    click.echo(f"Default provider: {cfg.default_provider}")
    click.echo(f"Default profile: {cfg.default_profile}")
    click.echo()

    click.echo("Providers:")
    for name, prov in cfg.providers.items():
        click.echo(f"  {name}:")
        click.echo(f"    base_url: {prov.base_url}")
        click.echo(f"    models: {', '.join(prov.models)}")
        click.echo(f"    api_key: {'***' if prov.api_key else '(none)'}")
    click.echo()

    click.echo("Profiles:")
    for name, prof in cfg.profiles.items():
        click.echo(f"  {name}: {prof}")


# ---------------------------------------------------------------------------
# kani init — generate a starter config
# ---------------------------------------------------------------------------

_STARTER_CONFIG = textwrap.dedent("""\
    # Kani Smart Router — Configuration
    # Docs: https://github.com/tumf/kani#configuration
    #
    # Env vars: use ${VAR_NAME} syntax for secrets.

    host: "0.0.0.0"
    port: 18420

    default_provider: openrouter
    default_profile: auto

    # ---------------------------------------------------------------------------
    # Providers — add your LLM backends here
    # ---------------------------------------------------------------------------
    providers:
      openrouter:
        name: openrouter
        base_url: "https://openrouter.ai/api/v1"
        api_key: "${OPENROUTER_API_KEY}"

    # ---------------------------------------------------------------------------
    # Routing Profiles
    # ---------------------------------------------------------------------------
    profiles:
      auto:
        tiers:
          SIMPLE:
            primary: "google/gemini-2.5-flash"
            fallback: []
            provider: default
          MEDIUM:
            primary: "anthropic/claude-sonnet-4"
            fallback:
              - "openai/gpt-4.1"
            provider: default
          COMPLEX:
            primary: "anthropic/claude-opus-4"
            fallback:
              - "openai/o3"
            provider: default
          REASONING:
            primary: "anthropic/claude-opus-4"
            fallback:
              - "openai/o3"
            provider: default
""")


@main.command("init")
@click.option(
    "--path",
    "output_path",
    default=None,
    help="Where to write config (default: XDG config dir)",
)
@click.option("--force", is_flag=True, help="Overwrite existing config")
def init_cmd(output_path: str | None, force: bool):
    """Create a starter configuration file."""
    from kani.dirs import config_dir

    if output_path:
        target = os.path.expanduser(output_path)
    else:
        target = str(config_dir() / "config.yaml")

    if os.path.exists(target) and not force:
        click.echo(f"Config already exists: {target}")
        click.echo("Use --force to overwrite.")
        raise SystemExit(1)

    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "w") as f:
        f.write(_STARTER_CONFIG)

    click.echo(f"Created starter config: {target}")
    click.echo()
    click.echo("Next steps:")
    click.echo("  1. Edit the config to add your API keys and preferred models")
    click.echo('  2. Run `kani route "hello"` to test routing')
    click.echo("  3. Run `kani serve` to start the proxy server")


# ---------------------------------------------------------------------------
# kani keys — API key management
# ---------------------------------------------------------------------------


@main.group("keys")
def keys_group():
    """Manage API keys for kani proxy access."""


@keys_group.command("add")
@click.argument("name")
def keys_add(name: str):
    """Create a new API key with the given NAME label."""
    from kani.api_keys import generate_key

    raw = generate_key(name)
    click.echo(f"Created API key: {name}")
    click.echo()
    click.echo(f"  {raw}")
    click.echo()
    click.echo("Save this key — it cannot be shown again.")


@keys_group.command("list")
def keys_list():
    """List all API keys (names and prefixes only)."""
    from kani.api_keys import list_keys

    entries = list_keys()
    if not entries:
        click.echo("No API keys configured. Use `kani keys add <name>` to create one.")
        return

    click.echo(f"{'NAME':<20} {'PREFIX':<12}")
    click.echo("-" * 32)
    for entry in entries:
        click.echo(f"{entry.name:<20} {entry.prefix:<12}")


@keys_group.command("remove")
@click.argument("identifier")
def keys_remove(identifier: str):
    """Remove an API key by NAME or PREFIX."""
    from kani.api_keys import remove_key

    if remove_key(identifier):
        click.echo(f"Removed API key: {identifier}")
    else:
        click.echo(f"No API key found matching: {identifier}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
