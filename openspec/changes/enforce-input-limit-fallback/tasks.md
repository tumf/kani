# Tasks

## Implementation Tasks

- [x] Remove the unsafe final selection fallback in `src/kani/router.py` that reuses `tier_cfg.resolve_primary_candidate_entries()` after input-limit filtering leaves no eligible candidates. (verification: unit evidence `tests/test_input_limit_routing.py::TestInputLimitRouting::test_raises_when_all_known_limit_candidates_are_over_limit`; implementation evidence `src/kani/router.py` raises `InputLimitNotSatisfiedError` instead of reusing original primaries)
- [x] Add or reuse a clear routing failure path for “no input-limit-eligible candidate” and ensure proxy/API error handling remains structured. (verification: unit/integration evidence `tests/test_input_limit_routing.py::TestInputLimitRouting::test_raises_when_all_known_limit_candidates_are_over_limit` and `tests/test_proxy_reload.py::TestProxyRoutingErrors::test_chat_completions_returns_structured_input_limit_error`; implementation evidence `src/kani/router.py` and `src/kani/proxy.py`)
- [x] Preserve valid fallback promotion when selected-tier primaries are over limit but selected-tier fallback candidates are eligible. (verification: unit evidence `tests/test_input_limit_routing.py::TestInputLimitRouting::test_fallback_can_satisfy_long_input`; implementation evidence `src/kani/router.py` uses eligible fallback candidates)
- [x] Preserve higher-tier promotion when selected-tier primary/fallback candidates are over limit but a higher-tier candidate is eligible. (verification: unit evidence `tests/test_input_limit_routing.py::TestInputLimitRouting::test_higher_tier_can_satisfy_long_input`; implementation evidence `src/kani/router.py` escalation path filters primary and fallback candidates by input limit)
- [x] Preserve unknown-limit backward compatibility: candidates without `max_input_tokens` remain eligible and can be selected when known-limit candidates are over limit. (verification: unit evidence `tests/test_input_limit_routing.py::TestInputLimitRouting::test_unknown_max_input_tokens_remains_eligible`; implementation evidence `src/kani/router.py::_filter_input_limit_candidates` keeps unknown-limit candidates eligible)
- [x] Keep cooldown ordering safe: if input-limit-eligible candidates are cooling down, cooldown fallback may ignore cooldown only among input-limit-eligible candidates and must not re-add known-over-limit candidates. (verification: unit evidence `tests/test_input_limit_routing.py::TestInputLimitRouting::test_cooldown_ignore_never_reintroduces_over_limit_candidate`; implementation evidence `src/kani/router.py` applies cooldown filtering after input-limit filtering)
- [x] Update routing logs/messages to avoid wording that implies kani will fall back to unsafe upstream handling after input-limit filtering. (verification: manual evidence `src/kani/router.py` log strings at input-limit failure/cooldown fallback paths plus focused command `uv run pytest tests/test_input_limit_routing.py tests/test_proxy_reload.py -q`)
- [x] Run focused and broad quality checks. (verification: integration - `uv run pytest tests/test_context_window_routing.py -q` or renamed focused test, `uv run ruff check src/`, `uv run ruff format --check src/ tests/`, `uv run pyright src/`, and `uv run pytest tests/ -q` pass)

## Future Work

- Operator policy for strict “unknown limit is ineligible” routing is out of scope and should be a separate proposal if needed.

## Final Validation

Expected archive gate: `cflx openspec validate enforce-input-limit-fallback --archive-gate`

## Acceptance #1 Failure Follow-up Resolution

Resolved the previous archive-gate blocker by adding repository-verifiable evidence to implementation task verification notes and retargeting the routing spec delta to canonical requirement `Input-limit-aware candidate selection`.

Final validation remains recorded in the non-checkbox `## Final Validation` section because archive validation is the authoritative gate.
