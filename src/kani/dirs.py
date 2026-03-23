"""XDG Base Directory paths for kani.

Always uses Linux-style XDG paths, even on macOS (ignores ~/Library/...):
- Config: $XDG_CONFIG_HOME/kani  (default: ~/.config/kani)
- Data:   $XDG_DATA_HOME/kani    (default: ~/.local/share/kani)
- Cache:  $XDG_CACHE_HOME/kani   (default: ~/.cache/kani)
- Logs:   $XDG_STATE_HOME/kani/log (default: ~/.local/state/kani/log)

All paths can be overridden with environment variables:
- KANI_CONFIG_DIR → config directory
- KANI_LOG_DIR    → log directory
- KANI_DATA_DIR   → data directory
"""

from __future__ import annotations

import os
from pathlib import Path


def _xdg_dir(env_var: str, default_subdir: str) -> Path:
    """Resolve an XDG directory, always using Linux-style defaults."""
    base = os.environ.get(env_var, "").strip()
    if not base:
        base = str(Path.home() / default_subdir)
    p = Path(base) / "kani"
    p.mkdir(parents=True, exist_ok=True)
    return p


def config_dir() -> Path:
    """Return the config directory for kani."""
    if env := os.environ.get("KANI_CONFIG_DIR"):
        return Path(env).expanduser()
    return _xdg_dir("XDG_CONFIG_HOME", ".config")


def log_dir() -> Path:
    """Return the log directory for kani."""
    if env := os.environ.get("KANI_LOG_DIR"):
        return Path(env).expanduser()
    return _xdg_dir("XDG_STATE_HOME", ".local/state") / "log"


def data_dir() -> Path:
    """Return the data directory for kani."""
    if env := os.environ.get("KANI_DATA_DIR"):
        return Path(env).expanduser()
    return _xdg_dir("XDG_DATA_HOME", ".local/share")
