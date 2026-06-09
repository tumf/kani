## Implementation Tasks

- [x] Task 1: Define diagnostic result data structures for checks, severity, and messages (verification: unit - `uv run pytest tests/test_cli.py -q -k doctor_result` asserts warning/error statuses serialize to readable lines without secrets)
- [x] Task 2: Add `kani doctor` command with `--config` support and read-only config loading (verification: integration - `uv run pytest tests/test_cli.py -q -k doctor_valid_config` uses Click runner with a fixture config and exits 0)
- [x] Task 3: Report providers/profiles/model metadata summary without raw `api_key` values (verification: integration - `uv run pytest tests/test_cli.py -q -k doctor_redacts_api_key` uses a config containing `sk-test-secret` and asserts the literal is absent)
- [x] Task 4: Detect `models/tier_classifier.pkl` and report it as legacy/unused unless runtime code explicitly loads it (verification: unit - `uv run pytest tests/test_cli.py -q -k doctor_tier_classifier_legacy` covers present and missing temp model paths)
- [x] Task 5: Detect `models/feature_classifier.pkl` and report it as present but not loaded by current runtime routing unless `src/kani/scorer.py` gains explicit loading evidence (verification: unit - `uv run pytest tests/test_cli.py -q -k doctor_feature_classifier_runtime_status` covers present and missing temp model paths)
- [x] Task 6: Return non-zero for invalid strict config and print `ConfigNotFoundError`/`ConfigIncompleteError` style messages without a traceback (verification: integration - `uv run pytest tests/test_cli.py -q -k doctor_invalid_config` uses Click runner with a missing config path and asserts non-zero exit)
- [x] Task 7: Run full lint/typecheck/test suite (verification: integration - `uv run ruff check src/`, `uv run pyright src/`, `uv run pytest tests/ -q` all pass)

## Future Work

- Add optional upstream provider reachability checks with safe timeouts.
- Add machine-readable JSON output mode if operators need automation.
- Add classifier format version markers if runtime classifier asset loading is reintroduced.

## Final Validation

Archive validation is the authoritative final OpenSpec validation gate.
Expected archive gate: `cflx openspec validate add-doctor-diagnostics --archive-gate`

## Acceptance #1 Failure Follow-up
- [x] src/kani/cli.py:111-126 misclassifies a valid legacy-only `model_capabilities` configuration as an error after `KaniConfig._normalize_legacy_model_capabilities` copies `model_capabilities` into `model_rules` (src/kani/config.py:354-363). Reproduction with a config containing only `model_capabilities` shows `kani doctor` exits non-zero and prints `[ERROR] model metadata: both model_rules and legacy model_capabilities are configured`, even though the base config spec requires legacy `model_capabilities` to be accepted and normalized when `model_rules` is unset (openspec/specs/config/spec.md:176-183). This conflicts with the change intent that doctor warnings should not fail by default and that model metadata surfaces are reported unambiguously (openspec/changes/add-doctor-diagnostics/proposal.md:30-34). Add implementation evidence that distinguishes raw config input from normalized config state, or otherwise report legacy-only metadata as a warning/status rather than a fatal ambiguity.
- [x] tests/test_cli.py:224-315 covers valid `model_rules`, secret redaction, invalid config, and classifier assets, but it does not cover the legacy-only `model_capabilities` scenario required by the existing config spec and targeted by the proposal's model metadata diagnostic. Add a Click runner test for a config with `model_capabilities` and no `model_rules` asserting exit 0 with a legacy metadata warning/status.
