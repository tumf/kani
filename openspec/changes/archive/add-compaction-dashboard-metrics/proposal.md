# Add compaction metrics to dashboard

## Problem / Context

The smart-proxy context compaction feature (Phase A sync + Phase B background) is fully operational, but its operational metrics are invisible in the kani dashboard. The original proposal's acceptance criteria explicitly require "dashboard-visible metrics so operators can observe hit rate, savings, and failure modes," yet:

1. `execution_logs` (the dashboard's backing table) has no compaction columns.
2. `execution-*.jsonl` (the intermediate log that feeds the dashboard) records no compaction fields.
3. The `COMPACTION` stderr log line includes `saved` tokens but omits the original token count, making reduction-rate calculation impossible.
4. `get_dashboard_stats()` and `render_dashboard_html()` have no compaction aggregates or visualisations.
5. The separate `compaction.db` stores per-session state but is not connected to the analytics pipeline.

Operators currently have no way to answer "how much is compaction saving me?" from the dashboard.

## Proposed Solution

Thread compaction metadata through the existing dashboard analytics pipeline without altering the separate `compaction.db` storage:

1. **Extend `log_execution_event()`** with compaction fields so every `execution-*.jsonl` record carries compaction outcome data.
2. **Add columns to `execution_logs`** via the existing migration pattern (`ALTER TABLE … ADD COLUMN`, ignore if exists).
3. **Update `ingest_execution_logs()`** to map the new JSONL fields into the new DB columns.
4. **Pass compaction result from proxy to `_log_usage()`** so the fields are populated on every routed request.
5. **Enrich stderr `COMPACTION` log** with `original_tokens` and `compacted_tokens` for grep-based debugging.
6. **Add compaction aggregates to `get_dashboard_stats()`**: per-window summaries and daily trend columns.
7. **Render compaction metrics in the HTML dashboard**: window cards, daily table columns, and a saved-tokens overlay on the trend chart.

## Acceptance Criteria

- Every routed request that passes through compaction logic records `compaction_mode`, `compaction_tokens_saved`, and `compaction_original_tokens` in the execution JSONL and dashboard DB.
- `GET /dashboard` shows compaction summary metrics (compacted request count, total saved tokens, compaction rate) in the window cards and daily rollup table.
- `GET /dashboard/stats` JSON includes compaction aggregates in `windows` and `daily_trends`.
- The stderr `COMPACTION` log line includes `original_tokens` and `compacted_tokens`.
- Existing dashboard functionality (routing stats, model usage, token trends) is unaffected.
- All new code passes lint, format, typecheck, and tests.

## Out of Scope

- Changes to `compaction.db` schema or the compaction algorithm itself.
- New dedicated compaction dashboard page or separate endpoint.
- Per-session compaction history view (future work).
- D3 chart for compaction trends as a dedicated graph (optional stretch; a simple overlay on the existing combined chart is sufficient).
