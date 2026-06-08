---
change_type: implementation
priority: medium
dependencies: []
references:
  - src/kani/config.py
  - src/kani/router.py
  - tests/test_context_window_routing.py
  - openspec/specs/routing/spec.md
  - openspec/specs/config/spec.md
  - config.yaml
  - config.example.yaml
  - README.md
---

# Rename model input-limit routing metadata to max_input_tokens

**Change Type**: implementation

## Problem / Context

kani currently names per-candidate input-size routing metadata `context_window_tokens`. The router estimates request prompt tokens and filters model candidates when `prompt_tokens > context_window_tokens`. That behavior is an input-token eligibility check, not a general context-window calculation.

The current name creates a misleading contract:

- `context_window_tokens` sounds like the model's full context window.
- The routing behavior only compares estimated input prompt tokens.
- Operators need a clear `max_input_tokens` field for input-size-based routing.

## Premise / Context

- Kani is a Python Click/FastAPI router/proxy with Pydantic config models in `src/kani/config.py` and routing selection in `src/kani/router.py`.
- Existing routing metadata is named `context_window_tokens`, but the behavior only compares estimated request prompt tokens against a per-candidate limit.
- Smart-proxy context compaction separately uses `smart_proxy.context_compaction.context_window_tokens` for threshold math and must not be renamed by this change.
- The requested artifact is an implementation proposal: source code, tests, docs/examples, and OpenSpec canonical requirements must move together.

## Proposed Solution

Rename the per-model routing metadata from `context_window_tokens` to `max_input_tokens` across runtime models, routing helpers, tests, example configs, docs, and OpenSpec.

The routing behavior remains the same: candidates with configured `max_input_tokens` lower than the estimated request prompt tokens are skipped before cooldown and selection.

Legacy routing metadata must not be silently ignored. The implementation must either reject legacy per-model `context_window_tokens` entries with a clear validation error, or accept them only through a short-lived migration path that maps them to `max_input_tokens` and emits an operator-visible deprecation warning.

## Acceptance Criteria

- `ModelEntry` accepts object entries containing `max_input_tokens` and preserves provider override behavior.
- `ResolvedModelCandidate` carries `max_input_tokens` through router candidate resolution.
- Routing skips candidates when `prompt_tokens > max_input_tokens`.
- Candidates without `max_input_tokens` remain eligible for backward compatibility with string entries and unannotated object entries.
- Legacy per-model `context_window_tokens` entries are not silently ignored.
- Capability filtering, fallback promotion, tier escalation, and cooldown behavior continue to work with the renamed field.
- Repository docs, examples, canonical specs, and tests no longer refer to `context_window_tokens` for this model input-limit routing feature.
- Smart-proxy compaction `context_window_tokens` remains unchanged and continues to mean the assumed context window for compaction threshold math.

## Explicit Completion Conditions

- `src/kani/config.py` exposes `max_input_tokens` on `ModelEntry` and `ResolvedModelCandidate` with positive integer validation equivalent to the old field.
- `src/kani/config.py` either rejects legacy model-entry `context_window_tokens` with a clear validation error or maps it to `max_input_tokens` with a deprecation warning; tests prove the chosen behavior.
- `src/kani/router.py` uses `max_input_tokens` names in helper names, variables, comments, and logs while preserving the input-token comparison behavior.
- `tests/test_context_window_routing.py` or its renamed equivalent verifies config parsing, primary skipping, unknown limit eligibility, fallback promotion, tier escalation, capability filtering, and cooldown ordering with `max_input_tokens`.
- `config.example.yaml`, README, and OpenSpec canonical specs are updated to use `max_input_tokens` for routing model metadata while retaining smart-proxy compaction `context_window_tokens` references; repository-local `config.yaml` is gitignored and only applicable when present in an operator workspace.
- Focused routing/config tests and broad quality checks pass.

## Out of Scope

- Changing token estimation semantics in `kani.compaction._estimate_tokens`.
- Adding automatic provider/model metadata discovery.
- Supporting both `context_window_tokens` and `max_input_tokens` as long-term aliases unless implementation chooses a short-lived compatibility path and tests it explicitly.
- Changing smart proxy compaction's separate `context_window_tokens` setting used for threshold math.
