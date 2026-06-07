---
change_type: implementation
priority: high
dependencies: []
references:
  - src/kani/config.py
  - src/kani/router.py
  - src/kani/compaction.py
  - tests/test_router_logging.py
  - openspec/specs/routing/spec.md
  - openspec/specs/config/spec.md
---

# Add context-window-aware routing

**Change Type**: implementation

## Premise / Context

- The user wants model selection to account for conversation context length.
- The clarified behavior is: when context is too long, smaller-context models must not be selected.
- `src/kani/router.py` currently selects candidates by profile/tier, capability filtering, fallback backoff, and round-robin, but not by model context window.
- `src/kani/config.py` currently allows model entries to declare `model` and optional `provider`; there is no per-candidate context window metadata.
- `src/kani/compaction.py::_estimate_tokens(messages, model)` already provides model-aware prompt token estimation with a fallback path.

## Problem / Context

Kani can route requests by complexity tier and capability, but it cannot avoid a configured model whose context window is too small for the current request. Operators can list both small local models and larger remote models in the same profile, but a long conversation may still route to the small model if it wins the tier/candidate selection path. That can cause avoidable upstream context-limit failures and defeats the user's requirement that long contexts should not select small models.

## Proposed Solution

Add optional per-model-entry context window metadata and use it during routing candidate filtering.

- Extend `ModelEntry` with `context_window_tokens: int | None`.
- Estimate request prompt tokens inside `Router.route()` using the existing `_estimate_tokens(messages, model)` helper.
- Filter candidates with configured `context_window_tokens` so candidates are eligible only when `prompt_tokens <= context_window_tokens`.
- Preserve backward compatibility by leaving candidates without `context_window_tokens` eligible.
- Apply context filtering after capability filtering and before cooldown / round-robin selection.
- If all primary candidates in the current tier are too small, consider fallback candidates and higher tiers using the same context eligibility rule.
- If no configured candidate has a known sufficient context window, leave unresolved over-limit handling to existing compaction/upstream behavior rather than adding a new error surface in this change.

## Acceptance Criteria

- A configured model candidate with `context_window_tokens` lower than the estimated prompt tokens is not selected as primary.
- A longer-context candidate in the same tier, fallback list, or higher tier can be selected when the smaller candidate is excluded.
- Candidates without `context_window_tokens` continue to behave as before for backward compatibility.
- Capability requirements remain mandatory; context filtering must not promote a candidate that lacks required capabilities.
- Fallback backoff cooldown still applies after context filtering.
- Round-robin state only rotates among currently eligible primary candidates.
- The example/default configuration can declare `context_window_tokens` for model object entries without breaking existing string entries.

## Explicit Completion Conditions

- `src/kani/config.py` accepts `context_window_tokens` on `{model, provider}` model entries and preserves existing string entry behavior.
- `src/kani/router.py` excludes too-small candidates using estimated request prompt tokens before final model selection.
- Router tests prove that a too-small model is not selected for long input and that a larger configured candidate is selected instead.
- Router tests prove that unset context windows remain eligible and that capability filtering remains enforced.
- Relevant verification commands pass: `uv run pytest tests/test_router_logging.py tests/test_capability_routing.py -q`, `uv run pyright src/`, and `uv run ruff check src/`.

## Out of Scope

- Live provider/model metadata discovery.
- Automatic context-window values for every model name.
- New OpenAI-compatible error types for all-candidates-too-small cases.
- Changing context compaction thresholds or compaction policy.
- Removing support for string model entries in config.
