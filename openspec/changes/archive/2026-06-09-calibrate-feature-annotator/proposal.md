---
change_type: implementation
priority: medium
dependencies: []
references:
  - https://github.com/tumf/kani/issues/2
  - src/kani/training_data.py
  - src/kani/scorer.py
  - tests/
---

# Calibrate Feature Annotator

**Change Type**: implementation

## Problem / Context

The offline feature annotator labels routing prompts with `low` / `medium` / `high` semantic dimensions for distilled feature training. Its current prompt names the dimensions but does not define calibration semantics, so annotator models can over-label dimensions as `high` and create poorly distributed training data.

## Proposed Solution

Add repo-derived calibration guidance to the `LLMFeatureAnnotator` prompt. Each semantic dimension should have concise conceptual `low`, `medium`, and `high` definitions aligned with kani's routing/scoring semantics.

The definitions must be authored from kani's own dimensions and expected routing behavior, not copied from a third-party issue comment or external model artifact. This is tracked in the routing spec because offline annotations produce the distilled routing features consumed by runtime routing.

## Acceptance Criteria

1. The offline annotator prompt includes calibration definitions for every semantic dimension in `SEMANTIC_DIMENSIONS`.
2. The prompt still requires JSON-only output with exactly the expected semantic dimension keys.
3. Representative dimensions such as `codePresence`, `reasoningMarkers`, and `agenticTask` are covered by tests.
4. Annotation response parsing and validation continue to reject missing or invalid labels as before; this change MUST NOT broaden or tighten the accepted output shape.
5. Runtime routing/proxy behavior is unchanged.

## Explicit Completion Conditions

- `src/kani/training_data.py` constructs or exposes an annotator prompt containing all semantic dimension definitions.
- Unit tests fail if representative calibration text is removed or if a semantic dimension lacks guidance.
- Existing training-data annotation parsing tests, or newly added equivalents, pass without changing accepted output shape.
- Relevant local verification commands complete successfully: targeted pytest for training-data tests, plus project lint/typecheck when implementation touches Python code.

## Out of Scope

- Importing third-party prompt text verbatim.
- Importing or trusting external classifier pickle files.
- Re-training or shipping a new classifier artifact.
- Changing runtime scoring thresholds or routing behavior.
