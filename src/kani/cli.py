"""kani CLI — serve, route, and inspect configuration."""

from __future__ import annotations

import json
import os

import click


def _resolve_config(ctx_config: str | None) -> str:
    """Return config path from CLI flag, env-var, or default."""
    if ctx_config:
        return ctx_config
    return os.environ.get("KANI_CONFIG", "./config.yaml")


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

    from kani.proxy import app, configure

    path = _resolve_config(config_path)
    configure(path)

    from kani.proxy import _config

    bind_host = host or (_config.host if _config else "0.0.0.0")
    bind_port = port or (_config.port if _config else 8000)

    click.echo(f"Starting kani proxy on {bind_host}:{bind_port}")
    click.echo(f"Config: {path}")

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

    path = _resolve_config(config_path)
    cfg = load_config(path)
    router = Router(cfg)

    messages = [{"role": "user", "content": prompt}]
    decision = router.route(messages, profile=profile)

    click.echo(json.dumps(decision.model_dump(), indent=2))


@main.command("config")
@click.option("--config", "config_path", default=None, help="Path to config.yaml")
def config_cmd(config_path: str | None):
    """Show current configuration."""
    from kani.config import load_config

    path = _resolve_config(config_path)
    cfg = load_config(path)

    click.echo(f"Config file: {path}")
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


if __name__ == "__main__":
    main()
