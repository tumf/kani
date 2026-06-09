---
change_type: implementation
priority: medium
dependencies: []
references:
  - src/kani/training_data.py
  - tests/test_agentic_training_data.py
  - openspec/specs/routing/spec.md
---

# Fix Training Data Calibration Import-Time Failure Scope

**Change Type**: implementation

## Problem / Context

`LLMFeatureAnnotator` builds its annotation prompt template at class definition time by calling the semantic-dimension calibration renderer. If `SEMANTIC_DIMENSIONS` changes without the calibration table being updated, importing `kani.training_data` can fail before callers can use unrelated helpers or handle annotation-specific failure paths.

## Proposed Solution

Defer semantic-dimension calibration text construction until annotation prompt construction time, while preserving the current prompt contract and validation behavior for actual LLM feature annotation.

## Acceptance Criteria

- Importing `kani.training_data` does not eagerly validate or render semantic calibration text.
- Annotation prompt construction still fails clearly when semantic calibration does not cover exactly the canonical semantic dimensions.
- The generated annotation prompt continues to include the complete prompt text without the old 2000-character truncation behavior.
- Parser tests reject schema drift such as extra JSON keys when the prompt contract requires exactly the semantic-dimension keys.

## Explicit Completion Conditions

- `src/kani/training_data.py` constructs the calibration portion lazily inside the annotation path or an equivalent cached helper, not at class definition/import time.
- `tests/test_agentic_training_data.py` includes behavior coverage for lazy calibration failure scoping, exact JSON key validation, and realistic non-truncated prompt input.
- Verification commands pass: `uv run pytest tests/test_agentic_training_data.py -q`, `uv run ruff check src/`, `uv run ruff format --check src/ tests/`, `uv run pyright src/`.

## Out of Scope

- Changing the canonical semantic dimension names or ordering.
- Changing routing scorer semantics outside training-data annotation.
