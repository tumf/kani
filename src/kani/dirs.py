"""XDG-compliant directory paths for kani.

Uses platformdirs for cross-platform XDG Base Directory support:
- Config: $XDG_CONFIG_HOME/kani  (e.g. ~/.config/kani)
- Data:   $XDG_DATA_HOME/kani    (e.g. ~/.local/share/kani)
- Cache:  $XDG_CACHE_HOME/kani   (e.g. ~/.cache/kani)
- Logs:   $XDG_STATE_HOME/kani/log (e.g. ~/.local/state/kani/log)

All paths can be overridden with environment variables:
- KANI_CONFIG_DIR → config directory
- KANI_LOG_DIR    → log directory
- KANI_DATA_DIR   → data directory
"""

from __future__ import annotations

import os
from pathlib import Path

from platformdirs import user_config_dir, user_data_dir, user_log_dir


def config_dir() -> Path:
    """Return the config directory for kani."""
    if env := os.environ.get("KANI_CONFIG_DIR"):
        return Path(env).expanduser()
    return Path(user_config_dir("kani", ensure_exists=True))


def log_dir() -> Path:
    """Return the log directory for kani."""
    if env := os.environ.get("KANI_LOG_DIR"):
        return Path(env).expanduser()
    return Path(user_log_dir("kani", ensure_exists=True))


def data_dir() -> Path:
    """Return the data directory for kani."""
    if env := os.environ.get("KANI_DATA_DIR"):
        return Path(env).expanduser()
    return Path(user_data_dir("kani", ensure_exists=True))
