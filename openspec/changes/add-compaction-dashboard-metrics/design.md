# Design: Compaction Dashboard Metrics

## Data Flow

```
proxy.py chat_completions()
  │
  ├── _resolve_compaction() → CompactionResult
  │     (mode, estimated_tokens_saved, session_id, session_mode)
  │
  ├── _proxy_upstream() → response with usage
  │
  └── _log_usage(compaction_mode=..., compaction_tokens_saved=..., ...)
        │
        ├── logger.info("USAGE ...") — unchanged
        ├── logger.info("COMPACTION ... original_tokens=N compacted_tokens=M") — enriched
        └── log_execution_event(compaction_mode=..., ...) → execution-YYYY-MM-DD.jsonl
                                                                    │
                                                          [on /dashboard access]
                                                                    │
                                                          ingest_execution_logs()
                                                                    │
                                                          execution_logs table
                                                          (+ new compaction columns)
                                                                    │
                                                          get_dashboard_stats()
                                                          (windows + daily_trends with compaction)
                                                                    │
                                                          render_dashboard_html()
                                                          (cards + table + JSON API)
```

## DB Schema Changes

### execution_logs — new columns (migration)

| Column | Type | Default | Description |
|--------|------|---------|-------------|
| `compaction_mode` | TEXT | NULL | off / skipped / inline / cached / failed |
| `compaction_tokens_saved` | INTEGER | 0 | Tokens saved by compaction |
| `compaction_original_tokens` | INTEGER | 0 | Pre-compaction token estimate |
| `compaction_session_id` | TEXT | NULL | Session ID (explicit or derived) |

Migration uses the existing pattern:

```python
try:
    conn.execute("ALTER TABLE execution_logs ADD COLUMN compaction_mode TEXT")
except sqlite3.OperationalError:
    pass  # column already exists
```

### Unique index update

The existing unique index `idx_execution_unique` is on `(timestamp, model, provider, profile, prompt_tokens, completion_tokens, total_tokens)`. Compaction columns do not need to be part of the unique constraint — a given request produces exactly one execution log row.

## API Changes

### log_execution_event() — new parameters

```python
def log_execution_event(
    *,
    # ... existing params ...
    compaction_mode: str | None = None,
    compaction_tokens_saved: int = 0,
    compaction_original_tokens: int = 0,
    compaction_session_id: str | None = None,
) -> None:
```

### _log_usage() — new parameters

```python
def _log_usage(
    # ... existing params ...
    compaction_mode: str | None = None,
    compaction_tokens_saved: int = 0,
    compaction_original_tokens: int = 0,
    compaction_session_id: str | None = None,
) -> None:
```

### get_dashboard_stats() — enriched return

```python
# In windows["24h"], windows["7d"], windows["30d"]:
{
    # ... existing fields ...
    "compaction_requests": int,       # requests with mode in (inline, cached)
    "compaction_tokens_saved": int,   # total saved tokens in window
}

# In daily_trends[]:
{
    # ... existing fields ...
    "compaction_requests": int,
    "compaction_tokens_saved": int,
}
```

## stderr Log Enrichment

Before:
```
COMPACTION mode=inline session=xxx snap=abc saved=68 request_id=yyy
```

After:
```
COMPACTION mode=inline session=xxx snap=abc saved=68 original_tokens=342 compacted_tokens=274 request_id=yyy
```

## Dashboard HTML Changes

### Window cards (`mini-grid`)

Add two rows to each card:
- **Compacted reqs** — count of requests where compaction was applied
- **Saved tokens** — total tokens saved in the window

### Daily rollup table

Add two columns:
- **Compacted** — count of compacted requests per day
- **Saved tokens** — sum of tokens saved per day

### JSON API (`/dashboard/stats`)

The new fields are included automatically since the JSON API returns `get_dashboard_stats()` verbatim.

## Design Decisions

1. **No changes to `compaction.db`**: The compaction DB stores session/snapshot/summary state for runtime. Dashboard metrics flow through the execution JSONL → dashboard DB pipeline, keeping concerns separated.

2. **No `compaction_session_mode` in DB**: Session mode (explicit/derived) is useful for debugging but low-value for aggregation. It is already in the response header and stderr log. Omitting it from the dashboard DB keeps the schema minimal.

3. **Compaction rate not stored, computed at query time**: `compaction_requests / execution_requests` is trivially computed in `_window_summary()` or by the frontend. No need to store it.

4. **Backward compatibility**: All new JSONL fields default to `None` / `0`. Existing JSONL files without compaction fields are ingested with `NULL` / `0` defaults. No data loss or migration required for historical data.
