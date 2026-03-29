## Implementation Tasks

- [ ] Task 1: Add config models and defaults for `smart_proxy.fallback_backoff` in `src/kani/config.py`, including `enabled`, `initial_delay_seconds`, `multiplier`, and `max_delay_seconds`, with config coverage for parsing and defaults. (verification: `uv run pytest tests/ -q -k config` and `uv run pyright src/`)
- [ ] Task 2: Add a process-local backoff state helper keyed by `model+provider` that records retryable failures, computes exponential cooldown windows, and resets streaks on success. (verification: targeted unit tests covering streak growth, max-delay clamp, and success reset)
- [ ] Task 3: Apply cooldown filtering to primary candidate selection in `src/kani/router.py` so cooled-down `model+provider` pairs are skipped before round-robin selection finalizes a candidate. (verification: router tests cover cooled primary skipping while preserving provider-specific isolation)
- [ ] Task 4: Apply cooldown filtering to fallback execution in `src/kani/proxy.py` so cooled-down fallback candidates are skipped without being retried during the cooldown window. (verification: proxy tests cover fallback skipping and the no-eligible-candidate case)
- [ ] Task 5: Record retryable failures and successful recoveries in the proxy request path so cooldown state changes reflect real non-streaming upstream outcomes and emit operational logs for apply/skip/reset events. (verification: proxy tests assert state transitions; logs remain non-blocking during failures)
- [ ] Task 6: Update OpenSpec and user-facing docs/examples to describe fallback backoff behavior and configuration. (verification: spec review plus relevant README/config example updates)
- [ ] Task 7: Run repo checks for the completed change. (verification: `uv run ruff check src/`, `uv run ruff format --check src/ tests/`, `uv run pyright src/`, `uv run pytest tests/ -q`, `uv build`)

## Future Work

- Consider durable/shared cooldown storage if kani later runs with multiple worker processes or multiple instances behind a load balancer.
- Consider internal diagnostics or dashboard surfacing for current cooldown entries if operators need live visibility.
