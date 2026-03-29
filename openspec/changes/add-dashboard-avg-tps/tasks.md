## Implementation Tasks

- [ ] Task 1: Extend model/provider usage aggregation in `src/kani/dashboard.py` so each grouped row includes `avg_tps`, computed as the arithmetic mean of per-request `total_tokens / (elapsed_ms / 1000)` for execution rows where `elapsed_ms > 0`. (verification: add/update `tests/test_dashboard.py` to assert the aggregated `avg_tps` value for seeded execution rows)

- [ ] Task 2: Update `_render_model_usage_table()` in `src/kani/dashboard.py` to append `AVG TPS` as the last table column and render `-` when `avg_tps` is absent. (verification: add/update `tests/test_dashboard.py` to assert the rendered table contains the `AVG TPS` header and expected cell values)

- [ ] Task 3: Run dashboard-focused verification and the required repo checks: `uv run pytest tests/test_dashboard.py -q`, `uv run ruff check src/`, `uv run ruff format --check src/ tests/`, and `uv run pyright src/`. (verification: all commands exit 0)

## Future Work

- If operators want a throughput-focused API surface later, expose `avg_tps` explicitly via `/dashboard/stats` documentation or other dashboard summary sections.
