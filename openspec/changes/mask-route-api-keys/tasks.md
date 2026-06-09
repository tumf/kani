## Implementation Tasks

- [ ] Task 1: Add a `_mask_keys_in_decision` helper to `src/kani/cli.py` that recursively replaces non-empty string values under the key `"api_key"` with `"***"` and preserves empty strings (verification: unit - `uv run pytest tests/test_cli.py -q -k mask_keys_in_decision` asserts nested top-level/fallback keys are masked and empty strings remain empty)
- [ ] Task 2: Apply the helper in the `route_cmd` function before `json.dumps(decision.model_dump(), ...)` (verification: integration - `uv run pytest tests/test_cli.py -q -k route_masks_api_key` uses Click runner with a secret fixture config and asserts the literal secret is absent while `"api_key": "***"` is present)
- [ ] Task 3: Add CLI regression tests in `tests/test_cli.py` covering top-level `api_key`, fallback `api_key`, and unset empty-string `api_key` behavior (verification: unit - `uv run pytest tests/test_cli.py -q` passes)
- [ ] Task 4: Run full lint/typecheck/test suite (verification: integration - `uv run ruff check src/`, `uv run pyright src/`, `uv run pytest tests/ -q` all pass)

## Future Work

- Consider adding `kani doctor` diagnostics as a separate change (tracked in `add-doctor-diagnostics`).
- Consider masking API keys in proxy HTTP logs or response bodies.

## Final Validation

Archive validation is the authoritative final OpenSpec validation gate.
Expected archive gate: `cflx openspec validate mask-route-api-keys --archive-gate`
