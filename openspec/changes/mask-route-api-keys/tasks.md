## Implementation Tasks

- [ ] Task 1: Add a `_mask_keys_in_decision` helper to `src/kani/cli.py` that recursively replaces dict values under the key `"api_key"` with `"***"` (verification: unit test — call helper on a dict with nested `api_key` fields and assert all become `"***"`)
- [ ] Task 2: Apply the helper in the `route_cmd` function before `json.dumps(decision.model_dump(), ...)` (verification: `uv run kani route "test"` outputs `"api_key": "***"` instead of the real key value)
- [ ] Task 3: Add a unit test in `tests/test_cli.py` for the mask helper covering top-level `api_key`, nested list entries, and values that are `None` (verification: `uv run pytest tests/test_cli.py -q` passes)
- [ ] Task 4: Run full lint/typecheck/test suite (verification: `uv run ruff check src/`, `uv run pyright src/`, `uv run pytest tests/ -q` all pass)

## Future Work

- Consider adding `kani doctor` diagnostics as a separate change (tracked in `add-doctor-diagnostics`).
- Consider masking API keys in proxy HTTP logs or response bodies.

## Final Validation

Archive validation is the authoritative final OpenSpec validation gate.
Expected archive gate: `cflx openspec validate mask-route-api-keys --archive-gate`
