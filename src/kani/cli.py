"""kani CLI — serve, route, and inspect configuration."""

from __future__ import annotations

import json
import os
import textwrap
from typing import NoReturn

import click

from kani.config import ConfigIncompleteError, ConfigNotFoundError


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
