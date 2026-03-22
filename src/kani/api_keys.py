"""API Key management for kani.

Keys are stored in the data directory as api_keys.json.
Each key has a name (label) and a hashed secret.
Auth is binary: valid key → access, invalid/missing → denied.
"""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
from dataclasses import dataclass
from pathlib import Path

from kani.dirs import data_dir

logger = logging.getLogger(__name__)

_KEYS_FILE = "api_keys.json"


@dataclass
class ApiKeyEntry:
    """A stored API key."""

    name: str
    key_hash: str
    prefix: str  # first 8 chars for identification


def _keys_path() -> Path:
    return data_dir() / _KEYS_FILE


def _hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def _load_keys() -> list[dict]:
    path = _keys_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
        if isinstance(data, list):
            return data
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to load API keys file: %s", exc)
    return []


def _save_keys(keys: list[dict]) -> None:
    path = _keys_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(keys, indent=2) + "\n")


def generate_key(name: str) -> str:
    """Create a new API key with the given name. Returns the raw key (shown once)."""
    raw = f"kani-{secrets.token_urlsafe(32)}"
    prefix = raw[:8]
    entry = {"name": name, "key_hash": _hash_key(raw), "prefix": prefix}

    keys = _load_keys()
    keys.append(entry)
    _save_keys(keys)

    logger.info("API key created: name=%s prefix=%s", name, prefix)
    return raw


def list_keys() -> list[ApiKeyEntry]:
    """Return all stored keys (without secrets)."""
    return [
        ApiKeyEntry(name=k["name"], key_hash=k["key_hash"], prefix=k["prefix"])
        for k in _load_keys()
        if "name" in k and "key_hash" in k and "prefix" in k
    ]


def remove_key(identifier: str) -> bool:
    """Remove a key by name or prefix. Returns True if removed."""
    keys = _load_keys()
    original_len = len(keys)
    keys = [
        k for k in keys if k.get("name") != identifier and k.get("prefix") != identifier
    ]
    if len(keys) < original_len:
        _save_keys(keys)
        logger.info("API key removed: %s", identifier)
        return True
    return False


def validate_key(raw: str) -> bool:
    """Check if a raw API key is valid."""
    h = _hash_key(raw)
    return any(k.get("key_hash") == h for k in _load_keys())


def has_keys() -> bool:
    """Return True if any API keys are configured."""
    return len(_load_keys()) > 0
