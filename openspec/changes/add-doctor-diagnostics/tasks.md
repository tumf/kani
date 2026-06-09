## Implementation Tasks

- [ ] Task 1: Define diagnostic result data structures for checks, severity, and messages (verification: unit - `uv run pytest tests/test_cli.py -q -k doctor_result` asserts warning/error statuses serialize to readable lines without secrets)
- [ ] Task 2: Add `kani doctor` command with `--config` support and read-only config loading (verification: integration - `uv run pytest tests/test_cli.py -q -k doctor_valid_config` uses Click runner with a fixture config and exits 0)
- [ ] Task 3: Report providers/profiles/model metadata summary without raw `api_key` values (verification: integration - `uv run pytest tests/test_cli.py -q -k doctor_redacts_api_key` uses a config containing `sk-test-secret` and asserts the literal is absent)
- [ ] Task 4: Detect `models/tier_classifier.pkl` and report it as legacy/unused unless runtime code explicitly loads it (verification: unit - `uv run pytest tests/test_cli.py -q -k doctor_tier_classifier_legacy` covers present and missing temp model paths)
- [ ] Task 5: Detect `models/feature_classifier.pkl` and report it as present but not loaded by current runtime routing unless `src/kani/scorer.py` gains explicit loading evidence (verification: unit - `uv run pytest tests/test_cli.py -q -k doctor_feature_classifier_runtime_status` covers present and missing temp model paths)
- [ ] Task 6: Return non-zero for invalid strict config and print `ConfigNotFoundError`/`ConfigIncompleteError` style messages without a traceback (verification: integration - `uv run pytest tests/test_cli.py -q -k doctor_invalid_config` uses Click runner with a missing config path and asserts non-zero exit)
- [ ] Task 7: Run full lint/typecheck/test suite (verification: integration - `uv run ruff check src/`, `uv run pyright src/`, `uv run pytest tests/ -q` all pass)

## Future Work

- Add optional upstream provider reachability checks with safe timeouts.
- Add machine-readable JSON output mode if operators need automation.
- Add classifier format version markers if runtime classifier asset loading is reintroduced.

## Final Validation

Archive validation is the authoritative final OpenSpec validation gate.
Expected archive gate: `cflx openspec validate add-doctor-diagnostics --archive-gate`
