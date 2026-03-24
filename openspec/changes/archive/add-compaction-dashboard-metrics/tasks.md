## Implementation Tasks

- [x] Task 1: Add compaction fields to `log_execution_event()` signature (`src/kani/dashboard.py`). Add `compaction_mode: str | None`, `compaction_tokens_saved: int`, `compaction_original_tokens: int`, `compaction_session_id: str | None` parameters and include them in the JSONL record dict. (verification: `uv run pytest tests/ -q -k dashboard`; inspect execution JSONL for new fields)

- [x] Task 2: Add `execution_logs` DB columns via migration (`src/kani/dashboard.py`). Add `ALTER TABLE ... ADD COLUMN` for `compaction_mode TEXT`, `compaction_tokens_saved INTEGER DEFAULT 0`, `compaction_original_tokens INTEGER DEFAULT 0`, `compaction_session_id TEXT` in `_init_dashboard_db()`. (verification: `uv run pytest tests/ -q`; confirm columns exist in fresh dashboard.db)

- [x] Task 3: Update `ingest_execution_logs()` to map new JSONL fields to DB columns (`src/kani/dashboard.py`). Read `compaction_mode`, `compaction_tokens_saved`, `compaction_original_tokens`, `compaction_session_id` from each JSONL record and insert into corresponding columns. (verification: write test JSONL record with compaction fields, ingest, query DB to confirm values)

- [x] Task 4: Thread compaction result through `_log_usage()` and proxy handler (`src/kani/proxy.py`). Add compaction parameters to `_log_usage()` and pass `compaction_result.mode`, `estimated_tokens_saved`, original prompt tokens, and `session_id` from `chat_completions` handler. (verification: start test kani, send compaction-triggering request, check execution JSONL has compaction fields)

- [x] Task 5: Enrich stderr `COMPACTION` log with `original_tokens` and `compacted_tokens` (`src/kani/proxy.py`). Add `original_tokens=N compacted_tokens=M` to `logger.info("COMPACTION mode=...")` calls for inline, cached, and skipped modes in `_resolve_compaction()`. (verification: grep test server logs for `original_tokens=` after a compaction request)

- [x] Task 6: Add compaction aggregates to `_window_summary()` (`src/kani/dashboard.py`). Query `execution_logs` for compacted request count and total saved tokens in each time window. Include `compaction_requests` and `compaction_tokens_saved` in returned dict. (verification: `uv run pytest tests/ -q -k dashboard`)

- [x] Task 7: Add compaction columns to `_daily_trends()` (`src/kani/dashboard.py`). Add `compaction_requests` and `compaction_tokens_saved` to the daily rollup query and returned dicts. (verification: `uv run pytest tests/ -q -k dashboard`)

- [x] Task 8: Update `_render_window_cards()` to show compaction metrics (`src/kani/dashboard.py`). Add "Compacted reqs" and "Saved tokens" rows to the `mini-grid` in each window card. (verification: start test kani, open `/dashboard`, confirm compaction rows in window cards)

- [x] Task 9: Update `_render_daily_table()` to include compaction columns (`src/kani/dashboard.py`). Add "Compacted" and "Saved tokens" columns to headers and row rendering. (verification: inspect `/dashboard` HTML for new columns in daily table)

- [x] Task 10: Ensure `get_dashboard_stats()` return includes compaction fields (`src/kani/dashboard.py`). Verify `windows` and `daily_trends` contain the new compaction aggregates. (verification: `curl /dashboard/stats | jq '.windows["24h"].compaction_tokens_saved'`)

- [x] Task 11: Add tests for compaction dashboard metrics (`tests/`). Cover `log_execution_event()` with compaction fields, `ingest_execution_logs()` mapping, `_window_summary()` and `_daily_trends()` aggregation, and proxy integration. (verification: `uv run pytest tests/ -q`)

- [x] Task 12: Run full CI suite and fix any issues. Run `uv run ruff check src/`, `uv run ruff format --check src/ tests/`, `uv run pyright src/`, `uv run pytest tests/ -q`. (verification: all commands exit 0)

## Future Work

- Per-session compaction history viewer in dashboard
- Dedicated D3 chart showing compaction savings trends over time
- Alert thresholds for compaction failure rate
