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
            ROUND(AVG(elapsed_ms), 1) AS avg_elapsed_ms,
            ROUND(
                AVG(
                    CASE
                        WHEN elapsed_ms > 0 THEN total_tokens / (elapsed_ms / 1000.0)
                    END
                ),
                1
            ) AS avg_tps
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
        return '<div class="text-muted-foreground text-center py-6 text-sm">No data yet</div>'

    max_value = max((int(item.get(value_key) or 0) for item in items), default=0) or 1
    rows: list[str] = []
    for item in items:
        label = escape(str(item.get(label_key, "-")))
        detail = escape(str(item.get(detail_key, ""))) if detail_key else ""
        value = int(item.get(value_key) or 0)
        width = 0 if value <= 0 else max(2, round((value / max_value) * 100))
        rows.append(
            """
            <div class="flex items-center gap-3 py-1.5">
                <div class="w-[140px] min-w-0 shrink-0">
                    <div class="text-sm font-medium text-foreground truncate">{label}</div>
                    {detail_html}
                </div>
                <div class="flex-1 h-2.5 bg-muted rounded-full overflow-hidden">
                    <div class="h-full rounded-full transition-all duration-300" style="width:{width}%; background:{color};"></div>
                </div>
                <div class="w-[70px] text-right text-sm tabular-nums text-muted-foreground">{value}</div>
            </div>
            """.format(
                label=label,
                detail_html=(
                    f'<div class="text-xs text-muted-foreground truncate">{detail}</div>'
                    if detail
                    else ""
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
            <div class="rounded-xl border border-border bg-card p-5 shadow-sm">
                <div class="text-sm font-medium text-muted-foreground">{escape(label)}</div>
                <div class="mt-1 text-3xl font-bold tracking-tight text-foreground">{escape(_fmt_int(item["routing_requests"]))}</div>
                <div class="text-xs text-muted-foreground mt-0.5">Routed requests</div>
                <div class="grid grid-cols-2 gap-x-4 gap-y-3 mt-4 pt-4 border-t border-border">
                    <div><span class="text-xs text-muted-foreground block">Usage rows</span><span class="text-sm font-semibold text-foreground">{escape(_fmt_int(item["execution_requests"]))}</span></div>
                    <div><span class="text-xs text-muted-foreground block">Input tokens</span><span class="text-sm font-semibold text-foreground">{escape(_fmt_int(item["prompt_tokens"]))}</span></div>
                    <div><span class="text-xs text-muted-foreground block">Output tokens</span><span class="text-sm font-semibold text-foreground">{escape(_fmt_int(item["completion_tokens"]))}</span></div>
                    <div><span class="text-xs text-muted-foreground block">Total tokens</span><span class="text-sm font-semibold text-foreground">{escape(_fmt_int(item["total_tokens"]))}</span></div>
                    <div><span class="text-xs text-muted-foreground block">Avg latency</span><span class="text-sm font-semibold text-foreground">{escape(_fmt_float(item["avg_elapsed_ms"]))} ms</span></div>
                    <div><span class="text-xs text-muted-foreground block">Coverage</span><span class="text-sm font-semibold text-foreground">{escape(_fmt_percent(item["usage_coverage"]))}</span></div>
                    <div><span class="text-xs text-muted-foreground block">Compacted</span><span class="text-sm font-semibold text-foreground">{escape(_fmt_int(item.get("compaction_requests", 0)))}</span></div>
                    <div><span class="text-xs text-muted-foreground block">Saved tokens</span><span class="text-sm font-semibold text-foreground">{escape(_fmt_int(item.get("compaction_tokens_saved", 0)))}</span></div>
                </div>
            </div>
            """
        )
    return "\n".join(cards)


def _render_simple_table(headers: list[str], rows: list[list[str]]) -> str:
    head = "".join(
        f'<th class="h-10 px-3 text-left align-middle text-xs font-medium text-muted-foreground uppercase tracking-wider">{escape(h)}</th>'
        for h in headers
    )
    if not rows:
        body = f'<tr><td colspan="{len(headers)}" class="text-center text-muted-foreground py-6 text-sm">No data yet</td></tr>'
    else:
        body = "\n".join(
            '<tr class="border-b border-border transition-colors hover:bg-muted/50">'
            + "".join(
                f'<td class="px-3 py-2.5 align-middle text-sm">{cell}</td>'
                for cell in row
            )
            + "</tr>"
            for row in rows
        )
    return (
        '<div class="w-full overflow-x-auto rounded-lg border border-border">'
        f'<table class="w-full min-w-[560px] caption-bottom text-sm"><thead class="bg-muted/50"><tr class="border-b border-border">{head}</tr></thead><tbody>{body}</tbody></table>'
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
                escape(_fmt_float(row.get("avg_tps"))),
            ]
        )
    return _render_simple_table(
        [
            "Model",
            "Provider",
            "Requests",
            "Input",
            "Output",
            "Total",
            "Avg latency",
            "AVG TPS",
        ],
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
        active_cls = (
            "border-primary bg-primary/10 text-primary"
            if checked
            else "border-border bg-card text-muted-foreground hover:bg-muted"
        )
        chips.append(
            f'<label class="inline-flex items-center gap-2 px-3 py-1.5 rounded-full border text-sm cursor-pointer transition-colors {active_cls}">'
            f'<input type="checkbox" name="profiles" value="{escape(profile)}"{checked_attr} class="accent-primary">'
            f"<span>{escape(profile)}</span></label>"
        )

    selection_label = "All profiles" if show_all else ", ".join(selected_profiles)
    clear_link = (
        '<a class="text-sm font-medium text-primary hover:underline" href="/dashboard">Clear</a>'
        if not show_all
        else ""
    )
    return (
        '<form class="rounded-xl border border-border bg-card p-5 shadow-sm mb-5" method="get" action="/dashboard">'
        '<div class="flex flex-wrap gap-3 justify-between items-start mb-3">'
        '<div><h2 class="text-base font-semibold text-foreground">Profiles</h2>'
        '<p class="text-xs text-muted-foreground mt-0.5">Filter by routing profile</p></div>'
        f'<div class="flex items-center gap-3">'
        f'<button type="submit" class="inline-flex items-center justify-center rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground shadow-sm hover:bg-primary/90 transition-colors cursor-pointer">Apply</button>'
        f"{clear_link}</div></div>"
        f'<div class="flex flex-wrap gap-2">{"".join(chips)}</div>'
        f'<div class="mt-3 text-xs text-muted-foreground">Showing: <strong class="text-foreground">{escape(selection_label)}</strong></div>'
        "</form>"
    )


def render_dashboard_html(stats: dict[str, Any]) -> str:
    """Render an HTML dashboard with shadcn/ui-inspired design."""
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

    # Crab icon for the logo and favicon.
    logo_svg = '<div class="flex h-8 w-8 items-center justify-center rounded-lg bg-primary text-xl leading-none text-primary-foreground shadow-sm">🦀</div>'

    # Theme toggle SVG icons
    sun_icon = '<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><circle cx="12" cy="12" r="5"/><path stroke-linecap="round" d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/></svg>'
    moon_icon = '<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>'

    parts = [
        "<!DOCTYPE html>",
        '<html lang="en" class="light">',
        "<head>",
        '    <meta charset="utf-8">',
        '    <meta name="viewport" content="width=device-width, initial-scale=1">',
        "    <title>Kani Dashboard</title>",
        '    <link rel="icon" href="data:image/svg+xml,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 32 32%22%3E%3Ctext x=%2216%22 y=%2224%22 text-anchor=%22middle%22 font-size=%2224%22%3E%F0%9F%A6%80%3C/text%3E%3C/svg%3E">',
        '    <script src="https://d3js.org/d3.v7.min.js"></script>',
        '    <script src="https://cdn.tailwindcss.com"></script>',
        "    <script>",
        "        tailwind.config = {",
        "            darkMode: 'class',",
        "            theme: { extend: {",
        "                colors: {",
        "                    border: 'hsl(var(--border))',",
        "                    input: 'hsl(var(--input))',",
        "                    ring: 'hsl(var(--ring))',",
        "                    background: 'hsl(var(--background))',",
        "                    foreground: 'hsl(var(--foreground))',",
        "                    primary: { DEFAULT: 'hsl(var(--primary))', foreground: 'hsl(var(--primary-foreground))' },",
        "                    secondary: { DEFAULT: 'hsl(var(--secondary))', foreground: 'hsl(var(--secondary-foreground))' },",
        "                    muted: { DEFAULT: 'hsl(var(--muted))', foreground: 'hsl(var(--muted-foreground))' },",
        "                    accent: { DEFAULT: 'hsl(var(--accent))', foreground: 'hsl(var(--accent-foreground))' },",
        "                    destructive: { DEFAULT: 'hsl(var(--destructive))', foreground: 'hsl(var(--destructive-foreground))' },",
        "                    card: { DEFAULT: 'hsl(var(--card))', foreground: 'hsl(var(--card-foreground))' },",
        "                },",
        "                borderRadius: { lg: 'var(--radius)', md: 'calc(var(--radius) - 2px)', sm: 'calc(var(--radius) - 4px)' },",
        "            }},",
        "        }",
        "    </script>",
        "    <style>",
        "        :root {",
        "            --background: 0 0% 100%;",
        "            --foreground: 222.2 84% 4.9%;",
        "            --card: 0 0% 100%;",
        "            --card-foreground: 222.2 84% 4.9%;",
        "            --primary: 221.2 83.2% 53.3%;",
        "            --primary-foreground: 210 40% 98%;",
        "            --secondary: 210 40% 96.1%;",
        "            --secondary-foreground: 222.2 47.4% 11.2%;",
        "            --muted: 210 40% 96.1%;",
        "            --muted-foreground: 215.4 16.3% 46.9%;",
        "            --accent: 210 40% 96.1%;",
        "            --accent-foreground: 222.2 47.4% 11.2%;",
        "            --destructive: 0 84.2% 60.2%;",
        "            --destructive-foreground: 210 40% 98%;",
        "            --border: 214.3 31.8% 91.4%;",
        "            --input: 214.3 31.8% 91.4%;",
        "            --ring: 221.2 83.2% 53.3%;",
        "            --radius: 0.75rem;",
        "            --chart-1: 221.2 83.2% 53.3%;",
        "            --chart-2: 262 83.3% 57.8%;",
        "            --chart-3: 142.1 76.2% 36.3%;",
        "            --chart-4: 38 92% 50%;",
        "            --chart-5: 196 100% 60%;",
        "        }",
        "        .dark {",
        "            --background: 222.2 84% 4.9%;",
        "            --foreground: 210 40% 98%;",
        "            --card: 222.2 84% 4.9%;",
        "            --card-foreground: 210 40% 98%;",
        "            --primary: 217.2 91.2% 59.8%;",
        "            --primary-foreground: 222.2 47.4% 11.2%;",
        "            --secondary: 217.2 32.6% 17.5%;",
        "            --secondary-foreground: 210 40% 98%;",
        "            --muted: 217.2 32.6% 17.5%;",
        "            --muted-foreground: 215 20.2% 65.1%;",
        "            --accent: 217.2 32.6% 17.5%;",
        "            --accent-foreground: 210 40% 98%;",
        "            --destructive: 0 62.8% 30.6%;",
        "            --destructive-foreground: 210 40% 98%;",
        "            --border: 217.2 32.6% 17.5%;",
        "            --input: 217.2 32.6% 17.5%;",
        "            --ring: 224.3 76.3% 48%;",
        "            --chart-1: 217.2 91.2% 59.8%;",
        "            --chart-2: 262 83.3% 67.8%;",
        "            --chart-3: 142.1 70.6% 45.3%;",
        "            --chart-4: 38 92% 60%;",
        "            --chart-5: 196 100% 70%;",
        "        }",
        "        * { box-sizing: border-box; margin: 0; }",
        "        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif; background: hsl(var(--background)); color: hsl(var(--foreground)); -webkit-font-smoothing: antialiased; }",
        "        .tabular-nums { font-variant-numeric: tabular-nums; }",
        "        /* D3 chart styles */",
        "        .trend-chart { width: 100%; min-height: 280px; position: relative; }",
        "        .trend-chart svg { width: 100%; height: auto; display: block; }",
        "        .trend-axis text, .trend-axis-label { fill: hsl(var(--muted-foreground)); font-size: 11px; font-family: inherit; }",
        "        .trend-axis path, .trend-axis line { stroke: hsl(var(--border)); }",
        "        .trend-grid line { stroke: hsl(var(--border)); stroke-dasharray: 3 3; }",
        "        .trend-grid path { stroke: none; }",
        "        .trend-point { filter: drop-shadow(0 2px 4px rgba(0,0,0,0.1)); }",
        "        .trend-tooltip { position: absolute; pointer-events: none; background: hsl(var(--foreground)); color: hsl(var(--background)); padding: 10px 14px; border-radius: var(--radius); box-shadow: 0 10px 30px rgba(0,0,0,0.2); font-size: 12px; line-height: 1.5; opacity: 0; transform: translate(-50%, calc(-100% - 14px)); transition: opacity 150ms ease; white-space: nowrap; z-index: 20; }",
        "        .trend-tooltip strong { display: block; font-size: 13px; margin-bottom: 3px; }",
        "        .trend-tooltip .trend-value { opacity: 0.8; font-variant-numeric: tabular-nums; display: block; }",
        "        @media (max-width: 640px) { .trend-chart { min-height: 220px; } .trend-tooltip { white-space: normal; max-width: calc(100vw - 2rem); } }",
        "    </style>",
        "</head>",
        '<body class="min-h-screen">',
        # ── Header ──
        '<header class="sticky top-0 z-50 w-full border-b border-border bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">',
        '    <div class="max-w-7xl mx-auto flex h-14 items-center justify-between px-4 sm:px-6 lg:px-8">',
        f'        <div class="flex items-center gap-3">{logo_svg}<span class="text-lg font-semibold tracking-tight">Kani</span><span class="hidden sm:inline-block text-sm text-muted-foreground font-normal">Dashboard</span></div>',
        '        <div class="flex items-center gap-3">',
        f'            <div class="hidden sm:flex items-center gap-2 text-xs text-muted-foreground"><svg class="w-3.5 h-3.5 text-emerald-500" fill="currentColor" viewBox="0 0 8 8"><circle cx="4" cy="4" r="3"/></svg>{escape(last_updated_relative)}</div>',
        f'            <button id="theme-toggle" class="inline-flex items-center justify-center rounded-md w-9 h-9 border border-border bg-background hover:bg-accent transition-colors cursor-pointer" aria-label="Toggle theme"><span id="theme-icon-light">{sun_icon}</span><span id="theme-icon-dark" class="hidden">{moon_icon}</span></button>',
        "        </div>",
        "    </div>",
        "</header>",
        # ── Main content ──
        '<main class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6 space-y-6">',
        # Status bar
        '    <div class="flex flex-wrap items-center gap-3">',
        f'        <div class="inline-flex items-center gap-2 rounded-full border border-border bg-card px-3 py-1.5 text-sm"><svg class="w-2.5 h-2.5 text-emerald-500" fill="currentColor" viewBox="0 0 8 8"><circle cx="4" cy="4" r="3"/></svg><span class="text-muted-foreground">Latest:</span><span class="font-medium">{escape(last_updated_relative)}</span></div>',
        f'        <span class="text-sm text-muted-foreground">Data through {escape(last_updated_label)}</span>',
        f'        <span class="text-sm text-muted-foreground">Profiles: <strong class="text-foreground">{escape(filter_summary)}</strong></span>',
        "    </div>",
        # Profile filter
        f"    {filter_html}",
        # Summary cards
        '    <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">',
        _render_window_cards(stats.get("windows", {})),
        "    </div>",
        # Charts section
        '    <div class="space-y-4">',
        '        <h2 class="text-xl font-semibold tracking-tight">Charts</h2>',
        '        <div class="grid grid-cols-1 lg:grid-cols-3 gap-4">',
        # Trend chart (full width)
        '            <div class="lg:col-span-3 rounded-xl border border-border bg-card p-5 shadow-sm relative overflow-hidden">',
        '                <h3 class="text-base font-semibold text-foreground">Requests & Token Usage (30d)</h3>',
        '                <p class="text-xs text-muted-foreground mt-0.5 mb-4">Daily routed requests overlaid with input/output token bars</p>',
        '                <div id="combined-trend-chart" class="trend-chart"></div>',
        '                <div class="trend-tooltip" id="combined-trend-chart-tooltip"></div>',
        "            </div>",
        # Bar charts
        f'            <div class="rounded-xl border border-border bg-card p-5 shadow-sm"><h3 class="text-base font-semibold text-foreground mb-3">Model Usage (7d)</h3>{_render_bar_chart(model_7d_chart_items, value_key="count", color="hsl(262, 83%, 58%)", detail_key="detail")}</div>',
        f'            <div class="rounded-xl border border-border bg-card p-5 shadow-sm"><h3 class="text-base font-semibold text-foreground mb-3">Tier Distribution ({escape(current_label)})</h3>{_render_bar_chart(tier_chart_items, value_key="count", color="hsl(221, 83%, 53%)")}</div>',
        f'            <div class="rounded-xl border border-border bg-card p-5 shadow-sm"><h3 class="text-base font-semibold text-foreground mb-3">Confidence ({escape(current_label)})</h3>{_render_bar_chart(confidence_chart_items, value_key="count", color="hsl(196, 100%, 60%)")}</div>',
        "        </div>",
        "    </div>",
        # Tier analytics
        '    <div class="space-y-4">',
        f'        <h2 class="text-xl font-semibold tracking-tight">Tier Analytics ({escape(current_label)})</h2>',
        '        <div class="grid grid-cols-1 md:grid-cols-2 gap-4">',
        f'            <div class="rounded-xl border border-border bg-card p-5 shadow-sm"><h3 class="text-base font-semibold text-foreground mb-3">Tier Distribution</h3>{_render_simple_table(["Tier", "Requests"], tier_rows)}</div>',
        f'            <div class="rounded-xl border border-border bg-card p-5 shadow-sm"><h3 class="text-base font-semibold text-foreground mb-3">Confidence Buckets</h3>{_render_simple_table(["Bucket", "Requests"], conf_rows)}</div>',
        "        </div>",
        f'        <div class="rounded-xl border border-border bg-card p-5 shadow-sm"><h3 class="text-base font-semibold text-foreground mb-3">Average Scores by Tier</h3>{_render_simple_table(["Tier", "Score", "Confidence", "Agentic"], avg_score_rows)}</div>',
        "    </div>",
        # Model usage tables
        '    <div class="space-y-4">',
        '        <h2 class="text-xl font-semibold tracking-tight">Model / Provider Usage</h2>',
        f'        <div class="rounded-xl border border-border bg-card p-5 shadow-sm"><h3 class="text-base font-semibold text-foreground mb-3">24h</h3>{_render_model_usage_table(stats.get("model_usage", {}).get("24h", []))}</div>',
        f'        <div class="rounded-xl border border-border bg-card p-5 shadow-sm"><h3 class="text-base font-semibold text-foreground mb-3">7d</h3>{_render_model_usage_table(stats.get("model_usage", {}).get("7d", []))}</div>',
        f'        <div class="rounded-xl border border-border bg-card p-5 shadow-sm"><h3 class="text-base font-semibold text-foreground mb-3">30d</h3>{_render_model_usage_table(stats.get("model_usage", {}).get("30d", []))}</div>',
        "    </div>",
        # Daily rollup
        '    <div class="space-y-4">',
        '        <h2 class="text-xl font-semibold tracking-tight">Daily Rollup (30d)</h2>',
        f'        <div class="rounded-xl border border-border bg-card p-5 shadow-sm">{_render_daily_table(stats.get("daily_trends", []))}</div>',
        "    </div>",
        "</main>",
        # Footer
        '<footer class="border-t border-border mt-8">',
        '    <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6 flex flex-wrap items-center justify-between gap-4 text-sm text-muted-foreground">',
        "        <span>Kani Router Dashboard</span>",
        '        <a class="hover:text-foreground transition-colors" href="https://github.com/tumf/kani" target="_blank" rel="noopener noreferrer">github.com/tumf/kani</a>',
        "    </div>",
        "</footer>",
        # Scripts
        "    <script>",
        # Theme toggle
        "        (function() {",
        "            const html = document.documentElement;",
        "            const toggle = document.getElementById('theme-toggle');",
        "            const iconLight = document.getElementById('theme-icon-light');",
        "            const iconDark = document.getElementById('theme-icon-dark');",
        "            function applyTheme(theme) {",
        "                html.classList.toggle('dark', theme === 'dark');",
        "                html.classList.toggle('light', theme !== 'dark');",
        "                if (iconLight && iconDark) { iconLight.classList.toggle('hidden', theme === 'dark'); iconDark.classList.toggle('hidden', theme !== 'dark'); }",
        "            }",
        "            const stored = localStorage.getItem('kani-theme');",
        "            const preferred = stored || (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');",
        "            applyTheme(preferred);",
        "            if (toggle) toggle.addEventListener('click', function() {",
        "                const next = html.classList.contains('dark') ? 'light' : 'dark';",
        "                localStorage.setItem('kani-theme', next);",
        "                applyTheme(next);",
        "                if (typeof renderAllTrendCharts === 'function') setTimeout(renderAllTrendCharts, 50);",
        "            });",
        "        })();",
        "    </script>",
        "    <script>",
        # D3 trend chart
        f"        const dailyTrends = {daily_trends_json};",
        "        const formatCompact = d3.format('~s');",
        "        function getChartColors() {",
        "            const isDark = document.documentElement.classList.contains('dark');",
        "            return {",
        "                request: isDark ? 'hsl(217, 91%, 60%)' : 'hsl(221, 83%, 53%)',",
        "                input: isDark ? 'hsl(142, 71%, 45%)' : 'hsl(142, 76%, 36%)',",
        "                output: isDark ? 'hsl(38, 92%, 60%)' : 'hsl(38, 92%, 50%)',",
        "                axis: isDark ? 'hsl(215, 20%, 65%)' : 'hsl(215, 16%, 47%)',",
        "                grid: isDark ? 'hsl(217, 33%, 18%)' : 'hsl(220, 13%, 91%)',",
        "                point: isDark ? 'hsl(222, 84%, 5%)' : '#ffffff',",
        "                hover: isDark ? 'hsl(215, 20%, 65%)' : '#98a2b3',",
        "            };",
        "        }",
        "        function renderCombinedTrendChart(containerId) {",
        "            const container = document.getElementById(containerId);",
        "            const tooltip = document.getElementById(`${containerId}-tooltip`);",
        "            if (!container) return;",
        "            if (!window.d3) { container.innerHTML = '<div class=\"text-muted-foreground text-center py-6 text-sm\">D3 failed to load</div>'; return; }",
        "            const colors = getChartColors();",
        "            const series = [",
        "                { key: 'prompt_tokens', label: 'Input tokens', color: colors.input },",
        "                { key: 'completion_tokens', label: 'Output tokens', color: colors.output },",
        "            ];",
        "            const requestColor = colors.request;",
        "            const data = dailyTrends.map((row) => ({",
        "                dayKey: row.day,",
        "                label: row.label,",
        "                requests: Number(row.requests || 0),",
        "                prompt_tokens: Number(row.prompt_tokens || 0),",
        "                completion_tokens: Number(row.completion_tokens || 0),",
        "            }));",
        "            if (!data.length) { container.innerHTML = '<div class=\"text-muted-foreground text-center py-6 text-sm\">No data yet</div>'; return; }",
        "            const width = Math.max(container.clientWidth || 360, 320);",
        "            const height = 320;",
        "            const margin = { top: 20, right: 60, bottom: 38, left: 56 };",
        "            const innerWidth = width - margin.left - margin.right;",
        "            const innerHeight = height - margin.top - margin.bottom;",
        "            container.innerHTML = '';",
        "            const svg = d3.select(container).append('svg').attr('viewBox', `0 0 ${width} ${height}`).attr('role', 'img').attr('aria-label', 'Requests line overlaid on input and output token bars over 30 days');",
        "            const g = svg.append('g').attr('transform', `translate(${margin.left},${margin.top})`);",
        "            const x = d3.scaleBand().domain(data.map((d) => d.dayKey)).range([0, innerWidth]).paddingInner(0.22);",
        "            const barX = d3.scaleBand().domain(series.map((s) => s.key)).range([0, x.bandwidth()]).padding(0.18);",
        "            const tokenMax = d3.max(data, (d) => d3.max(series, (s) => d[s.key])) || 1;",
        "            const requestMax = d3.max(data, (d) => d.requests) || 1;",
        "            const tokenY = d3.scaleLinear().domain([0, tokenMax * 1.12]).nice().range([innerHeight, 0]);",
        "            const requestY = d3.scaleLinear().domain([0, requestMax * 1.12]).nice().range([innerHeight, 0]);",
        "            const visibleTicks = data.map((_, i) => i).filter((i) => i === 0 || i === data.length - 1 || i % 5 === 0).map((i) => data[i].dayKey);",
        "            g.append('g').attr('class', 'trend-grid').call(d3.axisLeft(tokenY).ticks(5).tickSize(-innerWidth).tickFormat(''));",
        "            g.append('g').attr('class', 'trend-axis').attr('transform', `translate(0,${innerHeight})`).call(d3.axisBottom(x).tickValues(visibleTicks).tickFormat((d) => String(d).slice(5)));",
        "            g.append('g').attr('class', 'trend-axis').call(d3.axisLeft(requestY).ticks(5).tickFormat((d) => d3.format(',')(d)));",
        "            g.append('g').attr('class', 'trend-axis').attr('transform', `translate(${innerWidth},0)`).call(d3.axisRight(tokenY).ticks(5).tickFormat((d) => formatCompact(d).replace('G', 'B')));",
        "            g.append('text').attr('class', 'trend-axis-label').attr('x', 0).attr('y', -6).text('Requests');",
        "            g.append('text').attr('class', 'trend-axis-label').attr('x', innerWidth).attr('y', -6).attr('text-anchor', 'end').text('Tokens');",
        "            const barGroups = g.append('g');",
        "            series.forEach((s) => {",
        "                barGroups.selectAll(`.trend-bar-${s.key}`).data(data).enter().append('rect').attr('class', `trend-bar trend-bar-${s.key}`).attr('x', (d) => x(d.dayKey) + barX(s.key)).attr('width', Math.max(3, barX.bandwidth())).attr('y', (d) => tokenY(d[s.key])).attr('height', (d) => innerHeight - tokenY(d[s.key])).attr('rx', 3).attr('fill', s.color).attr('fill-opacity', 0.85);",
        "            });",
        "            const requestLine = d3.line().x((d) => x(d.dayKey) + x.bandwidth() / 2).y((d) => requestY(d.requests)).curve(d3.curveCatmullRom.alpha(0.5));",
        "            g.append('path').datum(data).attr('fill', 'none').attr('stroke', requestColor).attr('stroke-width', 2.5).attr('stroke-linecap', 'round').attr('stroke-linejoin', 'round').attr('d', requestLine);",
        "            const requestDots = g.append('g').selectAll('.trend-point').data(data).enter().append('circle').attr('class', 'trend-point').attr('cx', (d) => x(d.dayKey) + x.bandwidth() / 2).attr('cy', (d) => requestY(d.requests)).attr('r', 3.5).attr('fill', colors.point).attr('stroke', requestColor).attr('stroke-width', 2);",
        "            const legend = g.append('g').attr('transform', `translate(${Math.max(0, innerWidth - 170)}, 4)`);",
        "            [{ label: 'Requests', color: requestColor }, ...series].forEach((s, idx) => {",
        "                const row = legend.append('g').attr('transform', `translate(0, ${idx * 18})`);",
        "                if (s.label === 'Requests') {",
        "                    row.append('line').attr('x1', -2).attr('x2', 8).attr('y1', 0).attr('y2', 0).attr('stroke', s.color).attr('stroke-width', 2.5).attr('stroke-linecap', 'round');",
        "                    row.append('circle').attr('cx', 3).attr('cy', 0).attr('r', 3).attr('fill', colors.point).attr('stroke', s.color).attr('stroke-width', 2);",
        "                } else {",
        "                    row.append('rect').attr('x', -2).attr('y', -5).attr('width', 10).attr('height', 10).attr('rx', 2).attr('fill', s.color);",
        "                }",
        "                row.append('text').attr('x', 12).attr('y', 4).attr('fill', colors.axis).style('font-size', '11px').text(s.label);",
        "            });",
        "            const hoverLine = g.append('line').attr('stroke', colors.hover).attr('stroke-width', 1).attr('stroke-dasharray', '3 3').attr('y1', 0).attr('y2', innerHeight).style('opacity', 0);",
        "            const overlay = g.append('rect').attr('width', innerWidth).attr('height', innerHeight).attr('fill', 'transparent').style('cursor', 'crosshair');",
        "            function indexFromPointer(px) { if (!data.length) return 0; const bw = innerWidth / Math.max(1, data.length); return Math.max(0, Math.min(data.length - 1, Math.round(px / bw - 0.5))); }",
        "            function showTooltip(event) {",
        "                const [px] = d3.pointer(event, overlay.node());",
        "                const idx = indexFromPointer(px);",
        "                const d = data[idx];",
        "                if (!d) return;",
        "                const cx = x(d.dayKey) + x.bandwidth() / 2;",
        "                hoverLine.attr('x1', cx).attr('x2', cx).style('opacity', 1);",
        "                requestDots.attr('r', (_, i) => i === idx ? 5.5 : 3.5);",
        "                tooltip.style.opacity = '1';",
        "                tooltip.innerHTML = `<strong>${d.label}</strong><span class='trend-value'>Requests: ${d3.format(',')(d.requests)}</span><span class='trend-value'>Input: ${d3.format(',')(d.prompt_tokens)}</span><span class='trend-value'>Output: ${d3.format(',')(d.completion_tokens)}</span>`;",
        "                tooltip.style.left = `${Math.max(18, Math.min(cx + margin.left, innerWidth + margin.left - 18))}px`;",
        "                tooltip.style.top = `${Math.max(6, Math.min(innerHeight + margin.top - 20, event.offsetY + margin.top))}px`;",
        "            }",
        "            overlay.on('mousemove', showTooltip).on('mouseenter', () => { tooltip.style.opacity = '1'; }).on('mouseleave', () => { tooltip.style.opacity = '0'; hoverLine.style('opacity', 0); requestDots.attr('r', 3.5); });",
        "        }",
        "        function renderAllTrendCharts() { renderCombinedTrendChart('combined-trend-chart'); }",
        "        renderAllTrendCharts();",
        "        let trendResizeTimer = null;",
        "        window.addEventListener('resize', () => { clearTimeout(trendResizeTimer); trendResizeTimer = setTimeout(renderAllTrendCharts, 150); });",
        "    </script>",
        "</body>",
        "</html>",
    ]
    return "\n".join(parts)
