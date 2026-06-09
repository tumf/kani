## Implementation Tasks

- [ ] Task 1: Define diagnostic result data structures for checks, severity, and messages (verification: unit - tests assert warning/error statuses serialize to readable lines without secrets)
- [ ] Task 2: Add `kani doctor` command with `--config` support and read-only config loading (verification: integration - Click runner invokes `doctor --config <fixture>` and exits 0 for valid config)
- [ ] Task 3: Report providers/profiles/model metadata summary without raw `api_key` values (verification: integration - test config containing `sk-test-secret` does not include that literal in doctor output)
- [ ] Task 4: Detect `models/tier_classifier.pkl` and `models/feature_classifier.pkl` and report legacy/unused/active status based on current runtime scorer behavior (verification: unit - tests with temp model paths cover present/missing legacy assets and expected warning text)
- [ ] Task 5: Return non-zero for invalid strict config and print `ConfigNotFoundError`/`ConfigIncompleteError` style messages (verification: integration - Click runner with missing config path exits non-zero)
- [ ] Task 6: Run full lint/typecheck/test suite (verification: `uv run ruff check src/`, `uv run pyright src/`, `uv run pytest tests/ -q` all pass)

## Future Work

- Add optional upstream provider reachability checks with safe timeouts.
- Add machine-readable JSON output mode if operators need automation.
- Add classifier format version markers if runtime classifier asset loading is reintroduced.

## Final Validation

Archive validation is the authoritative final OpenSpec validation gate.
Expected archive gate: `cflx openspec validate add-doctor-diagnostics --archive-gate`
