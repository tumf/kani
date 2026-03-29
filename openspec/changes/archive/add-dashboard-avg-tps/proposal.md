# Add AVG TPS column to dashboard model/provider usage

## Problem / Context

The dashboard already shows model/provider usage across 24h, 7d, and 30d windows, including request counts, token totals, and average latency. However, operators cannot directly compare throughput efficiency between model/provider pairs from the dashboard table alone.

Today, an operator viewing `Model / Provider Usage` must mentally combine `total_tokens` and `avg_elapsed_ms` or inspect raw execution logs to estimate throughput. This makes quick operational comparison harder than necessary.

## Proposed Solution

Add a final `AVG TPS` column to each `Model / Provider Usage` table (`24h`, `7d`, `30d`) and compute it from execution analytics.

Recommended definition:

1. For each execution row with a positive `elapsed_ms`, compute per-request TPS as `total_tokens / (elapsed_ms / 1000)`.
2. For each `(model, provider)` group, report the arithmetic mean of those per-request TPS values.
3. Keep the existing `Avg latency` column unchanged.
4. Render `-` when no valid positive-latency execution rows exist for a group.

This keeps the metric aligned with operator intuition for an "average TPS" column while preserving the existing table structure and ordering.

## Acceptance Criteria

- `GET /dashboard` shows an `AVG TPS` column as the last column in each `Model / Provider Usage` table (`24h`, `7d`, `30d`).
- The `AVG TPS` value is computed as the mean of per-request `total_tokens / elapsed_seconds` for rows with `elapsed_ms > 0`.
- Rows with missing or non-positive latency data render `-` for `AVG TPS` instead of failing or showing invalid numeric output.
- Existing columns (`Model`, `Provider`, `Requests`, `Input`, `Output`, `Total`, `Avg latency`) remain present and keep their current meaning.
- Dashboard tests cover the stats aggregation and HTML rendering for the new column.

## Out of Scope

- Adding AVG TPS to summary cards, trend charts, or `/dashboard/stats` fields unrelated to model/provider usage.
- Reordering the existing table or changing the current ranking logic.
- Changing the meaning of `Avg latency`.
