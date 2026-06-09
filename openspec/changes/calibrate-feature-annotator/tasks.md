## Implementation Tasks

- [x] Add a complete semantic-dimension calibration map for offline annotation in `src/kani/training_data.py`. Verification: unit - tests assert every `SEMANTIC_DIMENSIONS` entry has calibration guidance. Completion condition: removing any dimension guidance causes a unit test failure.

- [x] Incorporate the calibration guidance into `LLMFeatureAnnotator`'s prompt while preserving JSON-only output requirements. Verification: unit - tests inspect the generated prompt/request body for representative dimensions and JSON-only instruction. Completion condition: the prompt includes `codePresence`, `reasoningMarkers`, and `agenticTask` definitions and still lists exactly the expected keys.

- [x] Preserve existing annotation parsing and label validation behavior without adding new rejection rules for extra JSON keys. Verification: unit - tests cover valid JSON labels and invalid/missing labels returning `None` or being rejected as before. Completion condition: response parsing behavior does not broaden or tighten accepted labels beyond current `low`, `medium`, `high` handling.

- [x] Confirm runtime routing/proxy behavior is unchanged. Verification: unit/manual - run existing relevant scorer/router/proxy tests or a targeted unchanged-behavior subset after the prompt-only change. Completion condition: runtime tests pass without changing routing thresholds, proxy payloads, or scorer outputs.

- [x] Run targeted and relevant project checks after implementation. Verification: manual - run targeted pytest for training-data/annotator tests; run ruff/pyright if Python code changed. Completion condition: command output shows no failures.

## Future Work

Re-annotating historical logs and retraining classifier artifacts is intentionally separate and should be proposed separately if needed.

## Final Validation

Expected archive gate: `cflx openspec validate calibrate-feature-annotator --archive-gate`.
