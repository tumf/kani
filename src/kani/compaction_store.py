"""Durable state storage for smart-proxy context compaction.

Manages session snapshots, token usage, summary cache, and job metadata
in a local SQLite database separate from the dashboard analytics store.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from pathlib import Path
from typing import Any

from kani.dirs import data_dir


# ── DB path ───────────────────────────────────────────────────────────────────

_COMPACTION_DB_PATH: Path | None = None


def _db_path() -> Path:
    global _COMPACTION_DB_PATH
    if _COMPACTION_DB_PATH is None:
        _COMPACTION_DB_PATH = data_dir() / "compaction.db"
    return _COMPACTION_DB_PATH


def set_db_path(path: Path) -> None:
    """Override DB path (for testing)."""
    global _COMPACTION_DB_PATH
    _COMPACTION_DB_PATH = path


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_db_path()), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


# ── Schema ────────────────────────────────────────────────────────────────────


def init_db() -> None:
    """Create compaction tables if they do not exist."""
    with _connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS compaction_sessions (
                session_id TEXT PRIMARY KEY,
                profile TEXT,
                last_request_id TEXT,
                latest_snapshot_hash TEXT,
                latest_prompt_tokens INTEGER DEFAULT 0,
                latest_total_tokens INTEGER DEFAULT 0,
                updated_at REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS compaction_snapshots (
                snapshot_hash TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                messages_json TEXT NOT NULL,
                prompt_tokens INTEGER DEFAULT 0,
                created_at REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS compaction_summaries (
                summary_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                snapshot_hash TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'queued',
                summary_text TEXT,
                estimated_tokens_saved INTEGER DEFAULT 0,
                error_message TEXT,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );
            """
        )


# ── Session helpers ───────────────────────────────────────────────────────────


def upsert_session(
    session_id: str,
    *,
    profile: str | None = None,
    request_id: str | None = None,
    snapshot_hash: str | None = None,
    prompt_tokens: int = 0,
    total_tokens: int = 0,
) -> None:
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO compaction_sessions
                (session_id, profile, last_request_id, latest_snapshot_hash,
                 latest_prompt_tokens, latest_total_tokens, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                profile = COALESCE(excluded.profile, profile),
                last_request_id = COALESCE(excluded.last_request_id, last_request_id),
                latest_snapshot_hash = COALESCE(excluded.latest_snapshot_hash, latest_snapshot_hash),
                latest_prompt_tokens = excluded.latest_prompt_tokens,
                latest_total_tokens = excluded.latest_total_tokens,
                updated_at = excluded.updated_at
            """,
            (
                session_id,
                profile,
                request_id,
                snapshot_hash,
                prompt_tokens,
                total_tokens,
                time.time(),
            ),
        )


def get_session(session_id: str) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM compaction_sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
    return dict(row) if row else None


# ── Snapshot helpers ──────────────────────────────────────────────────────────


def snapshot_hash(messages: list[dict[str, Any]]) -> str:
    """Compute a deterministic hash for a message list."""
    serialized = json.dumps(messages, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(serialized.encode()).hexdigest()[:32]


def save_snapshot(
    session_id: str,
    messages: list[dict[str, Any]],
    prompt_tokens: int = 0,
) -> str:
    """Persist a snapshot and return its hash."""
    h = snapshot_hash(messages)
    with _connect() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO compaction_snapshots
                (snapshot_hash, session_id, messages_json, prompt_tokens, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (h, session_id, json.dumps(messages), prompt_tokens, time.time()),
        )
    return h


def get_snapshot(snap_hash: str) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM compaction_snapshots WHERE snapshot_hash = ?", (snap_hash,)
        ).fetchone()
    return dict(row) if row else None


# ── Summary helpers ───────────────────────────────────────────────────────────


def get_ready_summary(session_id: str, snap_hash: str) -> dict[str, Any] | None:
    """Return the most recent ready summary for this session+snapshot, or None."""
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT * FROM compaction_summaries
            WHERE session_id = ? AND snapshot_hash = ? AND status = 'ready'
            ORDER BY updated_at DESC LIMIT 1
            """,
            (session_id, snap_hash),
        ).fetchone()
    return dict(row) if row else None


def get_inflight_summary(session_id: str, snap_hash: str) -> bool:
    """Return True if there is already a queued or running summary for this snapshot."""
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT 1 FROM compaction_summaries
            WHERE session_id = ? AND snapshot_hash = ? AND status IN ('queued', 'running')
            LIMIT 1
            """,
            (session_id, snap_hash),
        ).fetchone()
    return row is not None


def enqueue_summary(session_id: str, snap_hash: str) -> str:
    """Insert a queued summary job and return its summary_id."""
    import uuid

    sid = uuid.uuid4().hex
    now = time.time()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO compaction_summaries
                (summary_id, session_id, snapshot_hash, status, created_at, updated_at)
            VALUES (?, ?, ?, 'queued', ?, ?)
            """,
            (sid, session_id, snap_hash, now, now),
        )
    return sid


def update_summary(
    summary_id: str,
    *,
    status: str,
    summary_text: str | None = None,
    estimated_tokens_saved: int = 0,
    error_message: str | None = None,
) -> None:
    with _connect() as conn:
        conn.execute(
            """
            UPDATE compaction_summaries SET
                status = ?,
                summary_text = COALESCE(?, summary_text),
                estimated_tokens_saved = ?,
                error_message = COALESCE(?, error_message),
                updated_at = ?
            WHERE summary_id = ?
            """,
            (
                status,
                summary_text,
                estimated_tokens_saved,
                error_message,
                time.time(),
                summary_id,
            ),
        )


def mark_stale_summaries(session_id: str, current_snap_hash: str) -> None:
    """Mark all non-current ready/queued/running summaries for this session as stale."""
    with _connect() as conn:
        conn.execute(
            """
            UPDATE compaction_summaries SET status = 'stale', updated_at = ?
            WHERE session_id = ? AND snapshot_hash != ? AND status IN ('ready', 'queued', 'running')
            """,
            (time.time(), session_id, current_snap_hash),
        )


# ── Session ID resolution ─────────────────────────────────────────────────────


def resolve_session_id(
    messages: list[dict[str, Any]],
    *,
    explicit_header: str | None = None,
    model: str = "",
) -> tuple[str, str]:
    """Resolve the session ID and return (session_id, resolution_mode).

    Priority:
    1. explicit header value
    2. deterministic fallback hash from model + message structure
    """
    if explicit_header and explicit_header.strip():
        return explicit_header.strip(), "explicit"

    # Derived: hash from model family + first/last user message content (structure only)
    structure_key = model + "||" + _message_structure_key(messages)
    derived = hashlib.sha256(structure_key.encode()).hexdigest()[:24]
    return derived, "derived"


def _message_structure_key(messages: list[dict[str, Any]]) -> str:
    """A lightweight structural fingerprint — first and last messages only."""
    if not messages:
        return ""
    parts: list[str] = []
    first = messages[0]
    parts.append(f"{first.get('role', '')[:8]}:{str(first.get('content', ''))[:64]}")
    if len(messages) > 1:
        last = messages[-1]
        parts.append(f"{last.get('role', '')[:8]}:{str(last.get('content', ''))[:64]}")
    return "|".join(parts)
