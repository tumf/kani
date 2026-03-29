## Implementation Tasks

- [x] Task 1: Add config models and defaults for `smart_proxy.fallback_backoff` in `src/kani/config.py`, including `enabled`, `initial_delay_seconds`, `multiplier`, and `max_delay_seconds`, with config coverage for parsing and defaults. (verification: `uv run pytest tests/test_fallback_backoff.py -q` and `uv run pyright src/`)
- [x] Task 2: Add a process-local backoff state helper keyed by `model+provider` that records retryable failures, computes exponential cooldown windows, and resets streaks on success. (verification: `uv run pytest tests/test_fallback_backoff.py -q`)
- [x] Task 3: Apply cooldown filtering to primary candidate selection in `src/kani/router.py` so cooled-down `model+provider` pairs are skipped before round-robin selection finalizes a candidate. (verification: `uv run pytest tests/test_router_logging.py -q`)
- [x] Task 4: Apply cooldown filtering to fallback execution in `src/kani/proxy.py` so cooled-down fallback candidates are skipped without being retried during the cooldown window. (verification: `uv run pytest tests/test_api_keys_proxy.py -q`)
- [x] Task 5: Record retryable failures and successful recoveries in the proxy request path so cooldown state changes reflect real non-streaming upstream outcomes and emit operational logs for apply/skip/reset events. (verification: `uv run pytest tests/test_api_keys_proxy.py -q` and `uv run pytest tests/test_proxy_reload.py -q`)
- [x] Task 6: Update OpenSpec and user-facing docs/examples to describe fallback backoff behavior and configuration. (verification: spec review plus `README.md` updates)
- [x] Task 7: Run repo checks for the completed change. (verification: `uv run ruff check src/ tests/`, `uv run ruff format --check src/ tests/`, `uv run pyright src/`, `uv run pytest tests/ -q`, `uv build`)

## Future Work

- Consider durable/shared cooldown storage if kani later runs with multiple worker processes or multiple instances behind a load balancer.
- Consider internal diagnostics or dashboard surfacing for current cooldown entries if operators need live visibility.

## Acceptance #1 Failure Follow-up

- [ ] Commit or revert the current implementation changes so `git status --porcelain` is empty before rerunning acceptance.
