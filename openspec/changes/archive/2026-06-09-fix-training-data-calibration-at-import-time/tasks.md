## Implementation Tasks

- [x] Defer calibration text rendering out of class definition/import time in `src/kani/training_data.py`. (verification: unit - `uv run pytest tests/test_agentic_training_data.py -q -k calibration`; completion: importing `kani.training_data` does not call `_semantic_dimension_calibration_text()` until annotation prompt construction.)
- [x] Enforce exact semantic-dimension JSON key validation in the LLM feature annotator parser. (verification: unit - `uv run pytest tests/test_agentic_training_data.py -q -k extra_json_keys`; completion: annotator responses containing keys outside `SEMANTIC_DIMENSIONS` return `None` or an equivalent parse failure.)
- [x] Strengthen prompt-length coverage with varied realistic input longer than 2000 characters. (verification: unit - `uv run pytest tests/test_agentic_training_data.py -q -k truncate`; completion: captured annotator prompt equals the original varied input and retains content beyond position 2000.)
- [x] Run formatting, lint, typecheck, and targeted tests for the changed module. (verification: integration - `uv run ruff check src/ && uv run ruff format --check src/ tests/ && uv run pyright src/ && uv run pytest tests/test_agentic_training_data.py -q`; completion: all commands exit successfully.)

## Future Work

- None.

## Final Validation

Expected archive gate: `cflx openspec validate fix-training-data-calibration-at-import-time --archive-gate`
