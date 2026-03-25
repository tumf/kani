"""Kani dashboard — routing analytics and metrics."""

from __future__ import annotations

import json
import sqlite3
from collections import deque
from datetime import datetime, timedelta, timezone
from html import escape
from typing import Any

from kani.config import load_config
from kani.dirs import data_dir, log_dir


# ── Dashboard Data Collection ──────────────────────────────────────────────

_DASHBOARD_DB_PATH = data_dir() / "dashboard.db"
_LOCAL_TZ = datetime.now().astimezone().tzinfo or timezone.utc
_EXECUTION_LOG_PREFIX = "execution-"


def _ensure_dashboard_db_path() -> None:
    """Ensure the DB path is a file path, not a directory from a previous bad run."""
    if _DASHBOARD_DB_PATH.exists() and not _DASHBOARD_DB_PATH.is_file():
        bad_path = _DASHBOARD_DB_PATH
        backup = bad_path.with_name(f"{bad_path.name}.bad")
        while backup.exists():
            backup = bad_path.with_name(f"{backup.name}.old")
        bad_path.replace(backup)


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def _ensure_column(
    conn: sqlite3.Connection, table: str, column: str, definition: str
) -> None:
    if column not in _table_columns(conn, table):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _init_dashboard_db() -> None:
    """Initialize SQLite database for dashboard analytics."""
    _ensure_dashboard_db_path()
    with sqlite3.connect(_DASHBOARD_DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS routing_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                tier TEXT NOT NULL,
                score REAL NOT NULL,
                confidence REAL NOT NULL,
                agentic_score REAL NOT NULL,
                model TEXT,
                provider TEXT,
                profile TEXT,
                signals TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS execution_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                request_id TEXT,
                tier TEXT,
                score REAL,
                confidence REAL,
                agentic_score REAL,
                model TEXT,
                provider TEXT,
                profile TEXT,
                prompt_tokens INTEGER DEFAULT 0,
                completion_tokens INTEGER DEFAULT 0,
                total_tokens INTEGER DEFAULT 0,
                elapsed_ms REAL
            )
            """
        )

        # Migrations for existing DBs
        _ensure_column(conn, "routing_logs", "model", "TEXT")
        _ensure_column(conn, "routing_logs", "provider", "TEXT")
        _ensure_column(conn, "routing_logs", "profile", "TEXT")
        _ensure_column(conn, "routing_logs", "signals", "TEXT")

        # Compaction metrics columns (added in add-compaction-dashboard-metrics)
        _ensure_column(conn, "execution_logs", "compaction_mode", "TEXT")
        _ensure_column(
            conn, "execution_logs", "compaction_tokens_saved", "INTEGER DEFAULT 0"
        )
        _ensure_column(
            conn, "execution_logs", "compaction_original_tokens", "INTEGER DEFAULT 0"
        )
        _ensure_column(conn, "execution_logs", "compaction_session_id", "TEXT")

        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_routing_timestamp ON routing_logs(timestamp)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_execution_timestamp ON execution_logs(timestamp)"
        )
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_execution_unique "
            "ON execution_logs(timestamp, model, provider, profile, prompt_tokens, completion_tokens, total_tokens)"
        )

        # Cleanup for earlier dashboard versions that allowed duplicate route rows.
        conn.execute(
            """
            DELETE FROM routing_logs
            WHERE id NOT IN (
                SELECT MIN(id)
                FROM routing_logs
                GROUP BY
                    timestamp,
                    tier,
                    score,
                    confidence,
                    agentic_score,
                    COALESCE(model, ''),
                    COALESCE(provider, ''),
                    COALESCE(profile, '')
            )
            """
        )
        conn.commit()


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts)
    except ValueError:
        return None


def recommended_dashboard_ingest_days(
    full_days: int = 30, incremental_days: int = 2
) -> int:
    """Use a full backfill only on an empty dashboard DB; otherwise ingest recent logs only."""
    _init_dashboard_db()
    with sqlite3.connect(_DASHBOARD_DB_PATH) as conn:
        routing_count = conn.execute("SELECT COUNT(*) FROM routing_logs").fetchone()[0]
        execution_count = conn.execute(
            "SELECT COUNT(*) FROM execution_logs"
        ).fetchone()[0]
    if routing_count == 0 and execution_count == 0:
        return full_days
    return incremental_days


def dashboard_needs_stderr_backfill() -> bool:
    """Only run stderr backfill when structured execution data is still absent."""
    _init_dashboard_db()
    with sqlite3.connect(_DASHBOARD_DB_PATH) as conn:
        execution_count = conn.execute(
            "SELECT COUNT(*) FROM execution_logs"
        ).fetchone()[0]
    return execution_count == 0


def _parse_proxy_log_timestamp(ts: str) -> str:
    parsed = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S,%f")
    parsed = parsed.replace(tzinfo=_LOCAL_TZ)
    return parsed.astimezone(timezone.utc).isoformat()


def _parse_kv_tokens(payload: str) -> dict[str, str]:
    data: dict[str, str] = {}
    for token in payload.strip().split():
        if "=" not in token:
            continue
        key, value = token.split("=", 1)
        data[key] = value
    return data


def _insert_routing_record(conn: sqlite3.Connection, record: dict[str, Any]) -> int:
    existing = conn.execute(
        """
        SELECT id
        FROM routing_logs
        WHERE timestamp = ?
          AND tier = ?
          AND score = ?
          AND confidence = ?
          AND agentic_score = ?
          AND COALESCE(model, '') = COALESCE(?, '')
          AND COALESCE(provider, '') = COALESCE(?, '')
          AND COALESCE(profile, '') = COALESCE(?, '')
        LIMIT 1
        """,
        (
            record["timestamp"],
            record["tier"],
            record["score"],
            record["confidence"],
            record["agentic_score"],
            record.get("model"),
            record.get("provider"),
            record.get("profile"),
        ),
    ).fetchone()
    if existing:
        return 0

    legacy_row = conn.execute(
        """
        SELECT id, signals
        FROM routing_logs
        WHERE timestamp = ?
          AND tier = ?
          AND score = ?
          AND confidence = ?
          AND agentic_score = ?
          AND (
                COALESCE(profile, '') = ''
             OR COALESCE(model, '') = ''
             OR COALESCE(provider, '') = ''
          )
        LIMIT 1
        """,
        (
            record["timestamp"],
            record["tier"],
            record["score"],
            record["confidence"],
            record["agentic_score"],
        ),
    ).fetchone()
    if legacy_row:
        existing_signals: dict[str, Any] = {}
        raw_signals = legacy_row[1]
        if raw_signals:
            try:
                parsed = json.loads(raw_signals)
                if isinstance(parsed, dict):
                    existing_signals = parsed
            except (TypeError, ValueError, json.JSONDecodeError):
                existing_signals = {}

        merged_signals = record.get("signals") or existing_signals
        before = conn.total_changes
        conn.execute(
            """
            UPDATE routing_logs
            SET model = COALESCE(NULLIF(model, ''), ?),
                provider = COALESCE(NULLIF(provider, ''), ?),
                profile = COALESCE(NULLIF(profile, ''), ?),
                signals = ?
            WHERE id = ?
            """,
            (
                record.get("model"),
                record.get("provider"),
                record.get("profile"),
                json.dumps(merged_signals, ensure_ascii=False),
                legacy_row[0],
            ),
        )
        return conn.total_changes - before

    before = conn.total_changes
    conn.execute(
        """
        INSERT INTO routing_logs
        (timestamp, tier, score, confidence, agentic_score, model, provider, profile, signals)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            record["timestamp"],
            record["tier"],
            record["score"],
            record["confidence"],
            record["agentic_score"],
            record.get("model"),
            record.get("provider"),
            record.get("profile"),
            json.dumps(record.get("signals", {}), ensure_ascii=False),
        ),
    )
    return conn.total_changes - before


def _insert_execution_record(conn: sqlite3.Connection, record: dict[str, Any]) -> int:
    before = conn.total_changes
    conn.execute(
        """
        INSERT OR IGNORE INTO execution_logs
        (
            timestamp,
            request_id,
            tier,
            score,
            confidence,
            agentic_score,
            model,
            provider,
            profile,
            prompt_tokens,
            completion_tokens,
            total_tokens,
            elapsed_ms,
            compaction_mode,
            compaction_tokens_saved,
            compaction_original_tokens,
            compaction_session_id
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            record["timestamp"],
            record.get("request_id"),
            record.get("tier"),
            record.get("score"),
            record.get("confidence"),
            record.get("agentic_score"),
            record.get("model"),
            record.get("provider"),
            record.get("profile"),
            int(record.get("prompt_tokens") or 0),
            int(record.get("completion_tokens") or 0),
            int(record.get("total_tokens") or 0),
            float(record["elapsed_ms"])
            if record.get("elapsed_ms") is not None
            else None,
            record.get("compaction_mode"),
            int(record.get("compaction_tokens_saved") or 0),
            int(record.get("compaction_original_tokens") or 0),
            record.get("compaction_session_id"),
        ),
    )
    return conn.total_changes - before


def ingest_jsonl_logs(days: int = 1) -> int:
    """Ingest routing JSONL logs into SQLite."""
    _init_dashboard_db()
    log_directory = log_dir()
    end_date = datetime.now(timezone.utc)

    count = 0
    with sqlite3.connect(_DASHBOARD_DB_PATH) as conn:
        for i in range(days + 1):
            target_date = end_date - timedelta(days=i)
            log_file = (
                log_directory / f"routing-{target_date.strftime('%Y-%m-%d')}.jsonl"
            )
            if not log_file.exists():
                continue

            with open(log_file, "r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        record = json.loads(line)
                        count += _insert_routing_record(
                            conn,
                            {
                                "timestamp": record["timestamp"],
                                "tier": record["tier"],
                                "score": record["score"],
                                "confidence": record["confidence"],
                                "agentic_score": record["agentic_score"],
                                "model": record.get("model"),
                                "provider": record.get("provider"),
                                "profile": record.get("profile"),
                                "signals": record.get("signals", {}),
                            },
                        )
                    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                        pass

        conn.commit()

    return count


def log_execution_event(
    *,
    timestamp: str | None = None,
    request_id: str | None = None,
    tier: str | None = None,
    score: float | None = None,
    confidence: float | None = None,
    agentic_score: float | None = None,
    model: str | None = None,
    provider: str | None = None,
    profile: str | None = None,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    total_tokens: int = 0,
    elapsed_ms: float | None = None,
    compaction_mode: str | None = None,
    compaction_tokens_saved: int = 0,
    compaction_original_tokens: int = 0,
    compaction_session_id: str | None = None,
) -> None:
    """Append a structured execution record for dashboard analytics."""
    try:
        log_directory = log_dir()
        log_directory.mkdir(parents=True, exist_ok=True)
        now = datetime.now(timezone.utc)
        event_ts = timestamp or now.isoformat()
        day = _parse_iso(event_ts) or now
        log_file = (
            log_directory / f"{_EXECUTION_LOG_PREFIX}{day.strftime('%Y-%m-%d')}.jsonl"
        )
        record = {
            "timestamp": event_ts,
            "request_id": request_id,
            "tier": tier,
            "score": score,
            "confidence": confidence,
            "agentic_score": agentic_score,
            "model": model,
            "provider": provider,
            "profile": profile,
            "prompt_tokens": int(prompt_tokens or 0),
            "completion_tokens": int(completion_tokens or 0),
            "total_tokens": int(total_tokens or 0),
            "elapsed_ms": float(elapsed_ms) if elapsed_ms is not None else None,
            "compaction_mode": compaction_mode,
            "compaction_tokens_saved": int(compaction_tokens_saved or 0),
            "compaction_original_tokens": int(compaction_original_tokens or 0),
            "compaction_session_id": compaction_session_id,
        }
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        # Dashboard logging should never break request handling.
        pass


def ingest_execution_logs(days: int = 30) -> int:
    """Ingest structured execution JSONL logs into SQLite."""
    _init_dashboard_db()
    log_directory = log_dir()
    end_date = datetime.now(timezone.utc)

    count = 0
    with sqlite3.connect(_DASHBOARD_DB_PATH) as conn:
        for i in range(days + 1):
            target_date = end_date - timedelta(days=i)
            log_file = (
                log_directory
                / f"{_EXECUTION_LOG_PREFIX}{target_date.strftime('%Y-%m-%d')}.jsonl"
            )
            if not log_file.exists():
                continue

            with open(log_file, "r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        record = json.loads(line)
                        count += _insert_execution_record(conn, record)
                    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                        pass
        conn.commit()

    return count


def _resolve_provider_name(
    entry_provider: str, tier_provider: str, default_provider: str
) -> str:
    if entry_provider:
        return entry_provider
    if tier_provider and tier_provider != "default":
        return tier_provider
    return default_provider


def _infer_provider(
    model: str | None, profile: str | None, tier: str | None
) -> str | None:
    if not model:
        return None
    try:
        cfg = load_config()
    except Exception:
        return None

    if profile and tier:
        profile_cfg = cfg.profiles.get(profile)
        if profile_cfg:
            tier_cfg = profile_cfg.tiers.get(tier)
            if tier_cfg:
                primary_model, primary_provider = tier_cfg.resolve_primary()
                if primary_model == model:
                    return _resolve_provider_name(
                        primary_provider, tier_cfg.provider, cfg.default_provider
                    )
                for fb_model, fb_provider in tier_cfg.resolve_fallbacks():
                    if fb_model == model:
                        return _resolve_provider_name(
                            fb_provider, tier_cfg.provider, cfg.default_provider
                        )

    for profile_cfg in cfg.profiles.values():
        for tier_cfg in profile_cfg.tiers.values():
            primary_model, primary_provider = tier_cfg.resolve_primary()
            if primary_model == model:
                return _resolve_provider_name(
                    primary_provider, tier_cfg.provider, cfg.default_provider
                )
            for fb_model, fb_provider in tier_cfg.resolve_fallbacks():
                if fb_model == model:
                    return _resolve_provider_name(
                        fb_provider, tier_cfg.provider, cfg.default_provider
                    )

    return cfg.default_provider


def ingest_stderr_proxy_logs() -> int:
    """Best-effort backfill from human-readable proxy logs.

    This is used only for pre-structured historical data before execution-*.jsonl
    existed. It pairs ROUTE and USAGE lines in order.
    """
    _init_dashboard_db()
    stderr_log = log_dir() / "launchd-stderr.log"
    if not stderr_log.exists():
        return 0

    pending_routes: deque[dict[str, Any]] = deque()
    pending_by_request_id: dict[str, dict[str, Any]] = {}
    count = 0

    with sqlite3.connect(_DASHBOARD_DB_PATH) as conn:
        with open(stderr_log, "r", encoding="utf-8", errors="replace") as f:
            for raw_line in f:
                line = raw_line.strip()
                if "[INFO] kani.proxy: ROUTE " in line:
                    ts, payload = line.split(" [INFO] kani.proxy: ROUTE ", 1)
                    data = _parse_kv_tokens(payload)
                    event = {
                        "timestamp": _parse_proxy_log_timestamp(ts),
                        "request_id": data.get("request_id"),
                        "model": data.get("model"),
                        "provider": data.get("provider"),
                        "tier": data.get("tier"),
                        "score": float(data["score"]) if data.get("score") else None,
                        "confidence": float(data["confidence"])
                        if data.get("confidence")
                        else None,
                        "agentic_score": float(data["agentic"])
                        if data.get("agentic")
                        else None,
                        "profile": data.get("profile"),
                        "signals": {},
                    }
                    count += _insert_routing_record(conn, event)
                    pending_routes.append(event)
                    if event.get("request_id"):
                        pending_by_request_id[event["request_id"]] = event
                    continue

                if "[INFO] kani.proxy: USAGE " not in line:
                    continue

                ts, payload = line.split(" [INFO] kani.proxy: USAGE ", 1)
                data = _parse_kv_tokens(payload)
                usage_ts = _parse_proxy_log_timestamp(ts)
                route_event: dict[str, Any] | None = None
                request_id = data.get("request_id")

                if request_id and request_id in pending_by_request_id:
                    route_event = pending_by_request_id.pop(request_id)
                    try:
                        pending_routes.remove(route_event)
                    except ValueError:
                        pass
                else:
                    matched_index: int | None = None
                    for idx, candidate in enumerate(pending_routes):
                        if candidate.get("profile") and data.get("profile"):
                            if candidate["profile"] != data["profile"]:
                                continue
                        matched_index = idx
                        break
                    if matched_index is not None:
                        route_event = pending_routes[matched_index]
                        del pending_routes[matched_index]
                        if route_event.get("request_id"):
                            pending_by_request_id.pop(route_event["request_id"], None)

                model = data.get("model") or (route_event or {}).get("model")
                profile = data.get("profile") or (route_event or {}).get("profile")
                tier = (route_event or {}).get("tier")
                provider = (
                    data.get("provider")
                    or (route_event or {}).get("provider")
                    or _infer_provider(model, profile, tier)
                )

                record = {
                    "timestamp": (route_event or {}).get("timestamp") or usage_ts,
                    "request_id": request_id or (route_event or {}).get("request_id"),
                    "tier": tier,
                    "score": (route_event or {}).get("score"),
                    "confidence": (route_event or {}).get("confidence"),
                    "agentic_score": (route_event or {}).get("agentic_score"),
                    "model": model,
                    "provider": provider,
                    "profile": profile,
                    "prompt_tokens": int(data.get("prompt", 0) or 0),
                    "completion_tokens": int(data.get("completion", 0) or 0),
                    "total_tokens": int(data.get("total", 0) or 0),
                    "elapsed_ms": float(data["elapsed_ms"])
                    if data.get("elapsed_ms")
                    else None,
                }
                count += _insert_execution_record(conn, record)
        conn.commit()

    return count


# ── Dashboard Queries ──────────────────────────────────────────────────────


def _normalize_profiles(profiles: list[str] | tuple[str, ...] | None) -> list[str]:
    if not profiles:
        return []

    normalized: list[str] = []
    seen: set[str] = set()
    for item in profiles:
        if item is None:
            continue
        for part in str(item).split(","):
            profile = part.strip()
            if not profile or profile in seen:
                continue
            seen.add(profile)
            normalized.append(profile)
    return normalized


def _profile_filter_clause(
    column: str, profiles: list[str] | tuple[str, ...] | None
) -> tuple[str, list[str]]:
    selected = _normalize_profiles(profiles)
    if not selected:
        return "", []
    placeholders = ", ".join("?" for _ in selected)
    return f" AND COALESCE({column}, '') IN ({placeholders})", selected


def _available_profiles(conn: sqlite3.Connection) -> list[str]:
    profiles: set[str] = set()
    try:
        cfg = load_config(strict=False)
        profiles.update(cfg.profiles.keys())
    except Exception:
        pass

    rows = conn.execute(
        """
        SELECT profile FROM routing_logs WHERE profile IS NOT NULL AND profile != ''
        UNION
        SELECT profile FROM execution_logs WHERE profile IS NOT NULL AND profile != ''
        ORDER BY profile ASC
        """
    ).fetchall()
    profiles.update(str(row[0]) for row in rows if row[0])
    return sorted(profiles)


def _window_summary(
    conn: sqlite3.Connection,
    hours: int,
    profiles: list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    profile_sql, profile_params = _profile_filter_clause("profile", profiles)
    routing_total = conn.execute(
        f"SELECT COUNT(*) AS count FROM routing_logs WHERE timestamp > ?{profile_sql}",
        (cutoff, *profile_params),
    ).fetchone()["count"]
    execution_row = conn.execute(
        f"""
        SELECT
            COUNT(*) AS execution_requests,
            COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
            COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
            COALESCE(SUM(total_tokens), 0) AS total_tokens,
            ROUND(AVG(elapsed_ms), 1) AS avg_elapsed_ms,
            COALESCE(SUM(CASE WHEN compaction_mode IN ('inline', 'cached') THEN 1 ELSE 0 END), 0) AS compaction_requests,
            COALESCE(SUM(compaction_tokens_saved), 0) AS compaction_tokens_saved
        FROM execution_logs
        WHERE timestamp > ?
        {profile_sql}
        """,
        (cutoff, *profile_params),
    ).fetchone()
    execution_requests = execution_row["execution_requests"] or 0
    coverage = 0.0
    if routing_total:
        coverage = min(1.0, execution_requests / routing_total)
    elif execution_requests:
        coverage = 1.0

    return {
        "hours": hours,
        "routing_requests": routing_total,
        "execution_requests": execution_requests,
        "prompt_tokens": execution_row["prompt_tokens"] or 0,
        "completion_tokens": execution_row["completion_tokens"] or 0,
        "total_tokens": execution_row["total_tokens"] or 0,
        "avg_elapsed_ms": execution_row["avg_elapsed_ms"],
        "usage_coverage": coverage,
        "compaction_requests": execution_row["compaction_requests"] or 0,
        "compaction_tokens_saved": execution_row["compaction_tokens_saved"] or 0,
    }


def _model_usage_rows(
    conn: sqlite3.Connection,
    hours: int,
    limit: int = 12,
    profiles: list[str] | tuple[str, ...] | None = None,
) -> list[dict[str, Any]]:
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    profile_sql, profile_params = _profile_filter_clause("profile", profiles)
    rows = conn.execute(
        f"""
        SELECT
            model,
            provider,
            COUNT(*) AS count,
            COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
            COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
            COALESCE(SUM(total_tokens), 0) AS total_tokens,
            ROUND(AVG(elapsed_ms), 1) AS avg_elapsed_ms
        FROM execution_logs
        WHERE timestamp > ?
          AND model IS NOT NULL
          {profile_sql}
        GROUP BY model, provider
        ORDER BY count DESC, total_tokens DESC, model ASC
        LIMIT ?
        """,
        (cutoff, *profile_params, limit),
    ).fetchall()
    return [dict(row) for row in rows]


def _daily_trends(
    conn: sqlite3.Connection,
    days: int = 30,
    profiles: list[str] | tuple[str, ...] | None = None,
) -> list[dict[str, Any]]:
    start = datetime.now(timezone.utc).date() - timedelta(days=days - 1)
    start_ts = datetime.combine(
        start, datetime.min.time(), tzinfo=timezone.utc
    ).isoformat()
    profile_sql, profile_params = _profile_filter_clause("profile", profiles)
    routing_rows = conn.execute(
        f"""
        SELECT substr(timestamp, 1, 10) AS day, COUNT(*) AS requests
        FROM routing_logs
        WHERE timestamp >= ?
          {profile_sql}
        GROUP BY day
        ORDER BY day ASC
        """,
        (start_ts, *profile_params),
    ).fetchall()
    execution_rows = conn.execute(
        f"""
        SELECT
            substr(timestamp, 1, 10) AS day,
            COUNT(*) AS execution_requests,
            COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
            COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
            COALESCE(SUM(total_tokens), 0) AS total_tokens,
            COALESCE(SUM(CASE WHEN compaction_mode IN ('inline', 'cached') THEN 1 ELSE 0 END), 0) AS compaction_requests,
            COALESCE(SUM(compaction_tokens_saved), 0) AS compaction_tokens_saved
        FROM execution_logs
        WHERE timestamp >= ?
          {profile_sql}
        GROUP BY day
        ORDER BY day ASC
        """,
        (start_ts, *profile_params),
    ).fetchall()

    routing_map = {row["day"]: row["requests"] for row in routing_rows}
    execution_map = {row["day"]: dict(row) for row in execution_rows}

    data: list[dict[str, Any]] = []
    for i in range(days):
        current = start + timedelta(days=i)
        day = current.isoformat()
        execution = execution_map.get(day, {})
        data.append(
            {
                "day": day,
                "label": current.strftime("%m-%d"),
                "requests": routing_map.get(day, 0),
                "execution_requests": execution.get("execution_requests", 0),
                "prompt_tokens": execution.get("prompt_tokens", 0),
                "completion_tokens": execution.get("completion_tokens", 0),
                "total_tokens": execution.get("total_tokens", 0),
                "compaction_requests": execution.get("compaction_requests", 0),
                "compaction_tokens_saved": execution.get("compaction_tokens_saved", 0),
            }
        )
    return data


def get_dashboard_stats(
    hours: int = 24,
    profiles: list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Get routing statistics for the dashboard."""
    _init_dashboard_db()
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    selected_profiles = _normalize_profiles(profiles)

    with sqlite3.connect(_DASHBOARD_DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        profile_sql, profile_params = _profile_filter_clause(
            "profile", selected_profiles
        )
        available_profiles = sorted(
            set(_available_profiles(conn)).union(selected_profiles)
        )

        total = conn.execute(
            f"SELECT COUNT(*) AS count FROM routing_logs WHERE timestamp > ?{profile_sql}",
            (cutoff, *profile_params),
        ).fetchone()["count"]

        tier_dist = conn.execute(
            f"""
            SELECT tier, COUNT(*) AS count
            FROM routing_logs
            WHERE timestamp > ?
            {profile_sql}
            GROUP BY tier
            ORDER BY count DESC
            """,
            (cutoff, *profile_params),
        ).fetchall()

        avg_scores = conn.execute(
            f"""
            SELECT
                tier,
                ROUND(AVG(score), 4) AS avg_score,
                ROUND(AVG(confidence), 4) AS avg_confidence,
                ROUND(AVG(agentic_score), 4) AS avg_agentic
            FROM routing_logs
            WHERE timestamp > ?
            {profile_sql}
            GROUP BY tier
            ORDER BY avg_score DESC, tier ASC
            """,
            (cutoff, *profile_params),
        ).fetchall()

        conf_dist = conn.execute(
            f"""
            SELECT
                CASE
                    WHEN confidence >= 0.9 THEN '90-100%'
                    WHEN confidence >= 0.8 THEN '80-90%'
                    WHEN confidence >= 0.7 THEN '70-80%'
                    ELSE 'below 70%'
                END AS bucket,
                COUNT(*) AS count
            FROM routing_logs
            WHERE timestamp > ?
            {profile_sql}
            GROUP BY bucket
            ORDER BY count DESC
            """,
            (cutoff, *profile_params),
        ).fetchall()

        windows = {
            "24h": _window_summary(conn, 24, selected_profiles),
            "7d": _window_summary(conn, 24 * 7, selected_profiles),
            "30d": _window_summary(conn, 24 * 30, selected_profiles),
        }

        model_usage = {
            "24h": _model_usage_rows(conn, 24, profiles=selected_profiles),
            "7d": _model_usage_rows(conn, 24 * 7, profiles=selected_profiles),
            "30d": _model_usage_rows(conn, 24 * 30, profiles=selected_profiles),
        }

        daily = _daily_trends(conn, days=30, profiles=selected_profiles)
        last_updated_at = conn.execute(
            f"""
            SELECT MAX(timestamp) AS ts
            FROM (
                SELECT MAX(timestamp) AS timestamp FROM routing_logs WHERE timestamp > ?{profile_sql}
                UNION ALL
                SELECT MAX(timestamp) AS timestamp FROM execution_logs WHERE timestamp > ?{profile_sql}
            )
            """,
            [cutoff, *profile_params, cutoff, *profile_params],
        ).fetchone()["ts"]

        return {
            "period_hours": hours,
            "total_requests": total,
            "available_profiles": available_profiles,
            "selected_profiles": selected_profiles,
            "tier_distribution": {row["tier"]: row["count"] for row in tier_dist},
            "avg_scores_by_tier": [dict(row) for row in avg_scores],
            "confidence_distribution": {
                row["bucket"]: row["count"] for row in conf_dist
            },
            "windows": windows,
            "model_usage": model_usage,
            "daily_trends": daily,
            "last_updated_at": last_updated_at,
        }


# ── HTML Dashboard UI ──────────────────────────────────────────────────────


def _fmt_int(value: Any) -> str:
    try:
        return f"{int(value or 0):,}"
    except (TypeError, ValueError):
        return "0"


def _fmt_float(value: Any, digits: int = 1) -> str:
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return "-"


def _fmt_percent(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value * 100:.0f}%"


def _fmt_last_updated(timestamp: str | None) -> str:
    parsed = _parse_iso(timestamp)
    if parsed is None:
        return "No data yet"
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    local = parsed.astimezone(_LOCAL_TZ)
    return local.strftime("%Y-%m-%d %H:%M:%S %Z")


def _fmt_relative_time(timestamp: str | None) -> str:
    parsed = _parse_iso(timestamp)
    if parsed is None:
        return "-"
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    delta = datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)
    seconds = max(0, int(delta.total_seconds()))
    if seconds < 10:
        return "just now"
    if seconds < 60:
        return f"{seconds}s ago"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} min ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h ago"
    days = hours // 24
    if days < 7:
        return f"{days}d ago"
    weeks = days // 7
    if weeks < 5:
        return f"{weeks}w ago"
    months = days // 30
    if months < 12:
        return f"{months}mo ago"
    years = days // 365
    return f"{years}y ago"


def _render_bar_chart(
    items: list[dict[str, Any]],
    *,
    value_key: str,
    color: str,
    label_key: str = "label",
    detail_key: str | None = None,
) -> str:
    if not items:
        return '<div class="empty">No data yet</div>'

    max_value = max((int(item.get(value_key) or 0) for item in items), default=0) or 1
    rows: list[str] = []
    for item in items:
        label = escape(str(item.get(label_key, "-")))
        detail = escape(str(item.get(detail_key, ""))) if detail_key else ""
        value = int(item.get(value_key) or 0)
        width = 0 if value <= 0 else max(2, round((value / max_value) * 100))
        rows.append(
            """
            <div class="bar-row">
                <div class="bar-label">
                    <strong>{label}</strong>
                    {detail_html}
                </div>
                <div class="bar-track">
                    <div class="bar-fill" style="width:{width}%; background:{color};"></div>
                </div>
                <div class="bar-value">{value}</div>
            </div>
            """.format(
                label=label,
                detail_html=(
                    f'<div class="bar-detail">{detail}</div>' if detail else ""
                ),
                width=width,
                color=color,
                value=escape(_fmt_int(value)),
            )
        )
    return "\n".join(rows)


def _render_window_cards(windows: dict[str, dict[str, Any]]) -> str:
    order = [("24h", "Last 24h"), ("7d", "Last 7d"), ("30d", "Last 30d")]
    cards: list[str] = []
    for key, label in order:
        item = windows[key]
        cards.append(
            f"""
            <div class="card">
                <h2>{escape(label)}</h2>
                <div class="stat">{escape(_fmt_int(item["routing_requests"]))}</div>
                <div class="meta">Routed requests</div>
                <div class="mini-grid">
                    <div><span>Actual usage rows</span><strong>{escape(_fmt_int(item["execution_requests"]))}</strong></div>
                    <div><span>Input tokens</span><strong>{escape(_fmt_int(item["prompt_tokens"]))}</strong></div>
                    <div><span>Output tokens</span><strong>{escape(_fmt_int(item["completion_tokens"]))}</strong></div>
                    <div><span>Total tokens</span><strong>{escape(_fmt_int(item["total_tokens"]))}</strong></div>
                    <div><span>Avg latency</span><strong>{escape(_fmt_float(item["avg_elapsed_ms"]))} ms</strong></div>
                    <div><span>Usage coverage</span><strong>{escape(_fmt_percent(item["usage_coverage"]))}</strong></div>
                    <div><span>Compacted reqs</span><strong>{escape(_fmt_int(item.get("compaction_requests", 0)))}</strong></div>
                    <div><span>Saved tokens</span><strong>{escape(_fmt_int(item.get("compaction_tokens_saved", 0)))}</strong></div>
                </div>
            </div>
            """
        )
    return "\n".join(cards)


def _render_simple_table(headers: list[str], rows: list[list[str]]) -> str:
    head = "".join(f"<th>{escape(h)}</th>" for h in headers)
    if not rows:
        body = (
            f'<tr><td colspan="{len(headers)}" class="empty-cell">No data yet</td></tr>'
        )
    else:
        body = "\n".join(
            "<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>"
            for row in rows
        )
    return (
        '<div class="table-wrap">'
        f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"
        "</div>"
    )


def _render_model_usage_table(rows: list[dict[str, Any]]) -> str:
    table_rows: list[list[str]] = []
    for row in rows:
        table_rows.append(
            [
                escape(str(row.get("model") or "-")),
                escape(str(row.get("provider") or "-")),
                escape(_fmt_int(row.get("count"))),
                escape(_fmt_int(row.get("prompt_tokens"))),
                escape(_fmt_int(row.get("completion_tokens"))),
                escape(_fmt_int(row.get("total_tokens"))),
                escape(f"{_fmt_float(row.get('avg_elapsed_ms'))} ms"),
            ]
        )
    return _render_simple_table(
        ["Model", "Provider", "Requests", "Input", "Output", "Total", "Avg latency"],
        table_rows,
    )


def _render_daily_table(rows: list[dict[str, Any]]) -> str:
    table_rows: list[list[str]] = []
    for row in rows:
        table_rows.append(
            [
                escape(row["day"]),
                escape(_fmt_int(row["requests"])),
                escape(_fmt_int(row["execution_requests"])),
                escape(_fmt_int(row["prompt_tokens"])),
                escape(_fmt_int(row["completion_tokens"])),
                escape(_fmt_int(row["total_tokens"])),
                escape(_fmt_int(row.get("compaction_requests", 0))),
                escape(_fmt_int(row.get("compaction_tokens_saved", 0))),
            ]
        )
    return _render_simple_table(
        [
            "Day",
            "Routed",
            "Usage rows",
            "Input",
            "Output",
            "Total",
            "Compacted",
            "Saved tokens",
        ],
        table_rows,
    )


def _render_profile_filters(
    available_profiles: list[str], selected_profiles: list[str]
) -> str:
    if not available_profiles:
        return ""

    selected_set = set(selected_profiles)
    show_all = not selected_set
    chips: list[str] = []
    for profile in available_profiles:
        checked = show_all or profile in selected_set
        checked_attr = " checked" if checked else ""
        active_class = " active" if checked else ""
        chips.append(
            f'<label class="filter-chip{active_class}"><input type="checkbox" name="profiles" value="{escape(profile)}"{checked_attr}><span>{escape(profile)}</span></label>'
        )

    selection_label = "All profiles" if show_all else ", ".join(selected_profiles)
    clear_link = (
        '<a class="filter-clear" href="/dashboard">Clear filter</a>'
        if not show_all
        else ""
    )
    return (
        '<form class="filter-form card" method="get" action="/dashboard">'
        '<div class="filter-head">'
        '<div><h2>Profiles</h2><div class="meta">Filter dashboard statistics by one or more routing profiles.</div></div>'
        f'<div class="filter-actions"><button type="submit">Apply filters</button>{clear_link}</div>'
        "</div>"
        f'<div class="filter-chip-group">{"".join(chips)}</div>'
        f'<div class="filter-selection">Showing: <strong>{escape(selection_label)}</strong></div>'
        "</form>"
    )


def render_dashboard_html(stats: dict[str, Any]) -> str:
    """Render a simple HTML dashboard."""
    tier_chart_items = [
        {"label": tier, "count": count}
        for tier, count in sorted(
            stats.get("tier_distribution", {}).items(),
            key=lambda item: item[1],
            reverse=True,
        )
    ]
    confidence_chart_items = [
        {"label": bucket, "count": count}
        for bucket, count in stats.get("confidence_distribution", {}).items()
    ]
    model_7d_chart_items = [
        {
            "label": row.get("model") or "-",
            "detail": row.get("provider") or "-",
            "count": row.get("count") or 0,
        }
        for row in stats.get("model_usage", {}).get("7d", [])[:8]
    ]
    daily_trends = stats.get("daily_trends", [])
    daily_trends_json = json.dumps(daily_trends, ensure_ascii=False)

    avg_score_rows = [
        [
            escape(str(row.get("tier") or "-")),
            escape(_fmt_float(row.get("avg_score"), 4)),
            escape(_fmt_float(row.get("avg_confidence"), 4)),
            escape(_fmt_float(row.get("avg_agentic"), 4)),
        ]
        for row in stats.get("avg_scores_by_tier", [])
    ]
    tier_rows = [
        [escape(tier), escape(_fmt_int(count))]
        for tier, count in stats.get("tier_distribution", {}).items()
    ]
    conf_rows = [
        [escape(bucket), escape(_fmt_int(count))]
        for bucket, count in stats.get("confidence_distribution", {}).items()
    ]

    current_label = f"Last {stats.get('period_hours', 24)} hours"
    last_updated_at = stats.get("last_updated_at")
    last_updated_label = _fmt_last_updated(last_updated_at)
    last_updated_relative = _fmt_relative_time(last_updated_at)
    available_profiles = list(stats.get("available_profiles", []))
    selected_profiles = list(stats.get("selected_profiles", []))
    filter_summary = (
        "All profiles" if not selected_profiles else ", ".join(selected_profiles)
    )
    filter_html = _render_profile_filters(available_profiles, selected_profiles)

    parts = [
        "<!DOCTYPE html>",
        "<html>",
        "<head>",
        '    <meta name="viewport" content="width=device-width, initial-scale=1">',
        "    <title>Kani Dashboard</title>",
        '    <link rel="icon" href="data:image/svg+xml,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 64 64%22%3E%3Ctext y=%2252%22 font-size=%2252%22%3E🦀%3C/text%3E%3C/svg%3E">',
        '    <script src="https://d3js.org/d3.v7.min.js"></script>',
        "    <style>",
        "        * { box-sizing: border-box; }",
        '        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 0; padding: 20px; background: #f5f7fb; color: #1f2937; }',
        "        .container { max-width: 1440px; margin: 0 auto; }",
        "        h1 { margin: 0 0 8px; line-height: 1.15; }",
        "        .subtitle { color: #667085; margin-bottom: 24px; line-height: 1.5; }",
        "        .cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 20px; margin: 20px 0; }",
        "        .card { min-width: 0; background: white; padding: 20px; border-radius: 12px; box-shadow: 0 6px 20px rgba(16, 24, 40, 0.08); border: 1px solid #e5e7eb; }",
        "        .card h2 { margin: 0 0 12px; font-size: 18px; line-height: 1.35; }",
        "        .card.span-full { grid-column: 1 / -1; }",
        "        .stat { font-size: 34px; font-weight: 700; color: #175cd3; word-break: break-word; }",
        "        .meta { color: #667085; font-size: 14px; margin-top: 6px; }",
        "        .mini-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px 16px; margin-top: 16px; }",
        "        .mini-grid span { display: block; font-size: 12px; color: #667085; }",
        "        .mini-grid strong { display: block; margin-top: 2px; font-size: 15px; overflow-wrap: anywhere; }",
        "        .status-row { display: flex; flex-wrap: wrap; gap: 12px; align-items: center; margin: 0 0 18px; color: #667085; font-size: 14px; }",
        "        .status-pill { display: inline-flex; gap: 8px; align-items: center; padding: 8px 12px; border-radius: 999px; background: #eef4ff; color: #175cd3; font-weight: 600; }",
        "        .status-pill strong { color: #101828; }",
        "        .filter-form { margin: 0 0 20px; }",
        "        .filter-head { display: flex; flex-wrap: wrap; gap: 12px; justify-content: space-between; align-items: flex-start; margin-bottom: 14px; }",
        "        .filter-actions { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; }",
        "        .filter-actions button { border: 0; border-radius: 10px; background: #175cd3; color: white; padding: 10px 14px; font-weight: 600; cursor: pointer; }",
        "        .filter-actions button:hover { background: #1849a9; }",
        "        .filter-clear { color: #175cd3; text-decoration: none; font-weight: 600; }",
        "        .filter-clear:hover { text-decoration: underline; }",
        "        .filter-chip-group { display: flex; flex-wrap: wrap; gap: 10px; }",
        "        .filter-chip { display: inline-flex; align-items: center; gap: 8px; padding: 10px 12px; border-radius: 999px; border: 1px solid #d0d5dd; background: #fff; color: #344054; cursor: pointer; }",
        "        .filter-chip.active { border-color: #b2ddff; background: #eff8ff; color: #175cd3; }",
        "        .filter-chip input { margin: 0; }",
        "        .filter-selection { margin-top: 14px; color: #667085; font-size: 14px; }",
        "        .section { margin: 28px 0; }",
        "        .section h2 { margin: 0 0 14px; font-size: 22px; line-height: 1.3; }",
        "        .section-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 20px; }",
        "        .table-wrap { width: 100%; overflow-x: auto; overflow-y: hidden; border: 1px solid #eef2f7; border-radius: 10px; -webkit-overflow-scrolling: touch; }",
        "        table { width: 100%; min-width: 560px; border-collapse: collapse; font-size: 14px; }",
        "        thead { background: #f8fafc; }",
        "        th, td { text-align: left; padding: 10px 12px; border-bottom: 1px solid #eef2f7; vertical-align: top; overflow-wrap: anywhere; }",
        "        th { color: #475467; font-weight: 600; }",
        "        tr:hover td { background: #fafcff; }",
        "        .empty, .empty-cell { color: #98a2b3; text-align: center; padding: 18px; }",
        "        .bar-row { display: grid; grid-template-columns: 140px minmax(0, 1fr) 70px; gap: 12px; align-items: center; margin: 10px 0; }",
        "        .bar-label { min-width: 0; font-size: 13px; overflow: hidden; }",
        "        .bar-label strong { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }",
        "        .bar-detail { color: #667085; font-size: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }",
        "        .bar-track { width: 100%; height: 12px; background: #eef2f7; border-radius: 999px; overflow: hidden; }",
        "        .bar-fill { height: 100%; border-radius: 999px; }",
        "        .bar-value { text-align: right; font-variant-numeric: tabular-nums; color: #475467; font-size: 13px; }",
        "        .trend-card { position: relative; overflow: hidden; }",
        "        .trend-card::before { content: ''; position: absolute; inset: 0; background: radial-gradient(circle at top right, rgba(23, 92, 211, 0.08), transparent 38%); pointer-events: none; }",
        "        .trend-chart { width: 100%; min-height: 280px; }",
        "        .trend-chart svg { width: 100%; height: auto; display: block; }",
        "        .trend-subtitle { color: #667085; font-size: 13px; margin: -4px 0 14px; line-height: 1.5; }",
        "        .trend-axis text, .trend-axis-label { fill: #667085; font-size: 12px; }",
        "        .trend-axis path, .trend-axis line { stroke: #d0d5dd; }",
        "        .trend-grid line { stroke: #eaecf0; stroke-dasharray: 4 4; }",
        "        .trend-grid path { stroke: none; }",
        "        .trend-tooltip { position: absolute; pointer-events: none; background: rgba(15, 23, 42, 0.94); color: white; padding: 10px 12px; border-radius: 10px; box-shadow: 0 10px 30px rgba(15, 23, 42, 0.24); font-size: 12px; line-height: 1.45; opacity: 0; transform: translate(-50%, calc(-100% - 16px)); transition: opacity 120ms ease; white-space: nowrap; z-index: 2; max-width: min(260px, calc(100vw - 32px)); }",
        "        .trend-tooltip strong { display: block; font-size: 13px; margin-bottom: 2px; }",
        "        .trend-tooltip .trend-value { color: #bfdbfe; font-variant-numeric: tabular-nums; }",
        "        .trend-point { filter: drop-shadow(0 4px 10px rgba(15, 23, 42, 0.15)); }",
        "        footer { margin-top: 40px; text-align: center; color: #667085; font-size: 14px; }",
        "        footer a { color: #175cd3; text-decoration: none; }",
        "        footer a:hover { text-decoration: underline; }",
        "        @media (max-width: 900px) { .section-grid { grid-template-columns: 1fr; } .card.span-full { grid-column: auto; } }",
        "        @media (max-width: 720px) { body { padding: 16px; } .cards, .section-grid { gap: 16px; } .card { padding: 16px; } .mini-grid { grid-template-columns: 1fr; } .bar-row { grid-template-columns: 1fr; gap: 8px; } .bar-value { text-align: left; } .bar-label strong, .bar-detail { white-space: normal; text-overflow: clip; } .trend-chart { min-height: 240px; } .trend-tooltip { white-space: normal; } table { min-width: 480px; font-size: 13px; } th, td { padding: 9px 10px; } }",
        "        @media (max-width: 480px) { body { padding: 12px; } h1 { font-size: 28px; } .subtitle, .status-row, .meta { font-size: 13px; } .stat { font-size: 30px; } .section h2 { font-size: 20px; } .status-pill { width: 100%; justify-content: center; } table { min-width: 420px; } }",
        "    </style>",
        "</head>",
        "<body>",
        '<div class="container">',
        "    <h1>🦀 Kani Dashboard</h1>",
        '    <div class="subtitle">Routing tiers + actual model/provider usage + token trends</div>',
        f'    <div class="status-row"><div class="status-pill">Latest traffic <strong>{escape(last_updated_relative)}</strong></div><div>Data through: {escape(last_updated_label)}</div><div>Profiles: <strong>{escape(filter_summary)}</strong></div></div>',
        filter_html,
        '    <div class="cards">',
        _render_window_cards(stats.get("windows", {})),
        "    </div>",
        '    <div class="section">',
        "        <h2>Graphs</h2>",
        '        <div class="section-grid">',
        '            <div class="card trend-card span-full"><h2>Requests / day + Input / Output tokens / day (30d)</h2><div class="trend-subtitle">Daily routed requests overlaid on top of daily input/output token bars across the last 30 days</div><div id="combined-trend-chart" class="trend-chart"></div><div class="trend-tooltip" id="combined-trend-chart-tooltip"></div></div>',
        f'            <div class="card"><h2>Actual model usage (7d)</h2>{_render_bar_chart(model_7d_chart_items, value_key="count", color="#7a5af8", detail_key="detail")}</div>',
        f'            <div class="card"><h2>Tier distribution ({escape(current_label)})</h2>{_render_bar_chart(tier_chart_items, value_key="count", color="#175cd3")}</div>',
        f'            <div class="card"><h2>Confidence buckets ({escape(current_label)})</h2>{_render_bar_chart(confidence_chart_items, value_key="count", color="#36bffa")}</div>',
        "        </div>",
        "    </div>",
        '    <div class="section">',
        f"        <h2>Tier analytics ({escape(current_label)})</h2>",
        '        <div class="section-grid">',
        f'            <div class="card"><h2>Tier distribution</h2>{_render_simple_table(["Tier", "Requests"], tier_rows)}</div>',
        f'            <div class="card"><h2>Confidence buckets</h2>{_render_simple_table(["Bucket", "Requests"], conf_rows)}</div>',
        f'            <div class="card span-full"><h2>Average scores by tier</h2>{_render_simple_table(["Tier", "Score", "Confidence", "Agentic"], avg_score_rows)}</div>',
        "        </div>",
        "    </div>",
        '    <div class="section">',
        "        <h2>Actual model / provider usage</h2>",
        '        <div class="section-grid">',
        f'            <div class="card span-full"><h2>24h</h2>{_render_model_usage_table(stats.get("model_usage", {}).get("24h", []))}</div>',
        f'            <div class="card span-full"><h2>7d</h2>{_render_model_usage_table(stats.get("model_usage", {}).get("7d", []))}</div>',
        f'            <div class="card span-full"><h2>30d</h2>{_render_model_usage_table(stats.get("model_usage", {}).get("30d", []))}</div>',
        "        </div>",
        "    </div>",
        '    <div class="section">',
        "        <h2>Daily rollup (30d)</h2>",
        f'        <div class="card">{_render_daily_table(stats.get("daily_trends", []))}</div>',
        "    </div>",
        "    <script>",
        f"        const dailyTrends = {daily_trends_json};",
        "        const formatCompact = d3.format('~s');",
        "        function renderCombinedTrendChart(containerId) {",
        "            const container = document.getElementById(containerId);",
        "            const tooltip = document.getElementById(`${containerId}-tooltip`);",
        "            if (!container) return;",
        "            if (!window.d3) { container.innerHTML = '<div class=\"empty\">D3 failed to load</div>'; return; }",
        "            const series = [",
        "                { key: 'prompt_tokens', label: 'Input tokens', color: '#12b76a' },",
        "                { key: 'completion_tokens', label: 'Output tokens', color: '#f79009' },",
        "            ];",
        "            const requestColor = '#175cd3';",
        "            const data = dailyTrends.map((row) => ({",
        "                dayKey: row.day,",
        "                label: row.label,",
        "                requests: Number(row.requests || 0),",
        "                prompt_tokens: Number(row.prompt_tokens || 0),",
        "                completion_tokens: Number(row.completion_tokens || 0),",
        "            }));",
        "            if (!data.length) { container.innerHTML = '<div class=\"empty\">No data yet</div>'; return; }",
        "            const width = Math.max(container.clientWidth || 360, 320);",
        "            const height = 320;",
        "            const margin = { top: 20, right: 60, bottom: 38, left: 56 };",
        "            const innerWidth = width - margin.left - margin.right;",
        "            const innerHeight = height - margin.top - margin.bottom;",
        "            container.innerHTML = '';",
        "            const svg = d3.select(container)",
        "                .append('svg')",
        "                .attr('viewBox', `0 0 ${width} ${height}`)",
        "                .attr('role', 'img')",
        "                .attr('aria-label', 'Requests line overlaid on input and output token bars over 30 days');",
        "            const g = svg.append('g').attr('transform', `translate(${margin.left},${margin.top})`);",
        "            const x = d3.scaleBand().domain(data.map((d) => d.dayKey)).range([0, innerWidth]).paddingInner(0.22);",
        "            const barX = d3.scaleBand().domain(series.map((s) => s.key)).range([0, x.bandwidth()]).padding(0.18);",
        "            const tokenMax = d3.max(data, (d) => d3.max(series, (s) => d[s.key])) || 1;",
        "            const requestMax = d3.max(data, (d) => d.requests) || 1;",
        "            const tokenY = d3.scaleLinear().domain([0, tokenMax * 1.12]).nice().range([innerHeight, 0]);",
        "            const requestY = d3.scaleLinear().domain([0, requestMax * 1.12]).nice().range([innerHeight, 0]);",
        "            const visibleTicks = data.map((_, index) => index).filter((index) => index === 0 || index === data.length - 1 || index % 5 === 0).map((index) => data[index].dayKey);",
        "            g.append('g').attr('class', 'trend-grid').call(d3.axisLeft(tokenY).ticks(5).tickSize(-innerWidth).tickFormat(''));",
        "            g.append('g').attr('class', 'trend-axis').attr('transform', `translate(0,${innerHeight})`).call(d3.axisBottom(x).tickValues(visibleTicks).tickFormat((d) => String(d).slice(5)));",
        "            g.append('g').attr('class', 'trend-axis').call(d3.axisLeft(requestY).ticks(5).tickFormat((d) => d3.format(',')(d)));",
        "            g.append('g').attr('class', 'trend-axis').attr('transform', `translate(${innerWidth},0)`).call(d3.axisRight(tokenY).ticks(5).tickFormat((d) => formatCompact(d).replace('G', 'B')));",
        "            g.append('text').attr('class', 'trend-axis-label').attr('x', 0).attr('y', -6).text('Requests');",
        "            g.append('text').attr('class', 'trend-axis-label').attr('x', innerWidth).attr('y', -6).attr('text-anchor', 'end').text('Tokens');",
        "            const barGroups = g.append('g');",
        "            series.forEach((s) => {",
        "                barGroups.selectAll(`.trend-bar-${s.key}`).data(data).enter().append('rect').attr('class', `trend-bar trend-bar-${s.key}`).attr('x', (d) => x(d.dayKey) + barX(s.key)).attr('width', Math.max(3, barX.bandwidth())).attr('y', (d) => tokenY(d[s.key])).attr('height', (d) => innerHeight - tokenY(d[s.key])).attr('rx', 3).attr('fill', s.color).attr('fill-opacity', 0.95);",
        "            });",
        "            const requestLine = d3.line().x((d) => x(d.dayKey) + x.bandwidth() / 2).y((d) => requestY(d.requests)).curve(d3.curveCatmullRom.alpha(0.5));",
        "            g.append('path').datum(data).attr('fill', 'none').attr('stroke', requestColor).attr('stroke-width', 3).attr('stroke-linecap', 'round').attr('stroke-linejoin', 'round').attr('d', requestLine);",
        "            const requestDots = g.append('g').selectAll('.trend-point').data(data).enter().append('circle').attr('class', 'trend-point').attr('cx', (d) => x(d.dayKey) + x.bandwidth() / 2).attr('cy', (d) => requestY(d.requests)).attr('r', 4).attr('fill', '#ffffff').attr('stroke', requestColor).attr('stroke-width', 2);",
        "            const legend = g.append('g').attr('transform', `translate(${Math.max(0, innerWidth - 170)}, 4)`);",
        "            [{ label: 'Requests', color: requestColor }, ...series].forEach((s, idx) => {",
        "                const row = legend.append('g').attr('transform', `translate(0, ${idx * 18})`);",
        "                if (s.label === 'Requests') {",
        "                    row.append('line').attr('x1', -2).attr('x2', 8).attr('y1', 0).attr('y2', 0).attr('stroke', s.color).attr('stroke-width', 3).attr('stroke-linecap', 'round');",
        "                    row.append('circle').attr('cx', 3).attr('cy', 0).attr('r', 3.5).attr('fill', '#ffffff').attr('stroke', s.color).attr('stroke-width', 2);",
        "                } else {",
        "                    row.append('rect').attr('x', -2).attr('y', -5).attr('width', 10).attr('height', 10).attr('rx', 2).attr('fill', s.color);",
        "                }",
        "                row.append('text').attr('x', 12).attr('y', 4).attr('fill', '#475467').style('font-size', '12px').text(`${s.label}`);",
        "            });",
        "            const hoverLine = g.append('line').attr('stroke', '#98a2b3').attr('stroke-width', 1.5).attr('stroke-dasharray', '4 4').attr('y1', 0).attr('y2', innerHeight).style('opacity', 0);",
        "            const overlay = g.append('rect').attr('width', innerWidth).attr('height', innerHeight).attr('fill', 'transparent').style('cursor', 'crosshair');",
        "            function indexFromPointer(pointerX) {",
        "                if (!data.length) return 0;",
        "                const bandwidth = innerWidth / Math.max(1, data.length);",
        "                const idx = Math.round(pointerX / bandwidth - 0.5);",
        "                return Math.max(0, Math.min(data.length - 1, idx));",
        "            }",
        "            function showTooltip(event) {",
        "                const [pointerX] = d3.pointer(event, overlay.node());",
        "                const idx = indexFromPointer(pointerX);",
        "                const d = data[idx];",
        "                if (!d) return;",
        "                const centerX = x(d.dayKey) + x.bandwidth() / 2;",
        "                hoverLine.attr('x1', centerX).attr('x2', centerX).style('opacity', 1);",
        "                requestDots.attr('r', (point, pointIdx) => pointIdx === idx ? 6 : 4);",
        "                tooltip.style.opacity = '1';",
        "                tooltip.innerHTML = `<strong>${d.label}</strong><span class='trend-value'>Requests: ${d3.format(',')(d.requests)}</span><span class='trend-value'>Input: ${d3.format(',')(d.prompt_tokens)}</span><span class='trend-value'>Output: ${d3.format(',')(d.completion_tokens)}</span>`;",
        "                tooltip.style.left = `${Math.max(18, Math.min(centerX + margin.left, innerWidth + margin.left - 18))}px`;",
        "                tooltip.style.top = `${Math.max(6, Math.min(innerHeight + margin.top - 20, event.offsetY + margin.top))}px`;",
        "            }",
        "            overlay.on('mousemove', showTooltip).on('mouseenter', () => { tooltip.style.opacity = '1'; }).on('mouseleave', () => { tooltip.style.opacity = '0'; hoverLine.style('opacity', 0); requestDots.attr('r', 4); });",
        "        }",
        "        function renderAllTrendCharts() {",
        "            renderCombinedTrendChart('combined-trend-chart');",
        "        }",
        "        renderAllTrendCharts();",
        "        let trendResizeTimer = null;",
        "        window.addEventListener('resize', () => { clearTimeout(trendResizeTimer); trendResizeTimer = setTimeout(renderAllTrendCharts, 120); });",
        "    </script>",
        "    <footer>",
        '        Source: <a href="https://github.com/tumf/kani" target="_blank" rel="noopener noreferrer">github.com/tumf/kani</a>',
        "    </footer>",
        "</div>",
        "</body>",
        "</html>",
    ]
    return "\n".join(parts)
