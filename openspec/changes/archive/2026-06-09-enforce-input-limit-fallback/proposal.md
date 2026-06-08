---
change_type: implementation
priority: medium
references:
  - src/kani/router.py
  - tests/test_context_window_routing.py
  - openspec/changes/archive/2026-06-09-rename-max-input-tokens
  - openspec/specs/routing/spec.md
---

# Enforce input-limit fallback instead of unsafe primary fallback

**Change Type**: implementation

## Premise / Context

- Kani routes requests through `src/kani/router.py`, estimating request prompt tokens with `_estimate_tokens(messages)` before candidate selection.
- The active `rename-max-input-tokens` proposal renames per-model routing metadata to `max_input_tokens` and defines it as an input-token eligibility limit.
- Current routing filters primary, fallback, and higher-tier candidates by the configured limit, but if no context-eligible candidate remains it falls back to the original tier primary entries.
- The user requirement is: when the input-token limit is exceeded, route to an eligible fallback instead of selecting an over-limit primary.

## Problem / Context

Input-limit routing should protect operators from sending oversized requests to models that are explicitly configured as too small for the request. The current implementation has a final safety escape hatch that reuses the original primary candidate list when every filtered candidate is empty. That behavior can re-select a candidate whose configured limit was already exceeded, making the input-limit metadata advisory rather than enforced.

## Proposed Solution

Make input-limit eligibility authoritative for annotated candidates. When the selected tier's primary candidates exceed their configured input limits, routing must try eligible fallback candidates and then eligible higher-tier candidates. If no eligible configured candidate exists, routing must fail with a structured routing error instead of selecting a candidate known to be over limit.

Candidates without `max_input_tokens` remain eligible for backward compatibility. This proposal does not require strict annotation of every model; it only prevents known-over-limit candidates from being selected after the filter has rejected them.

## Acceptance Criteria

- A primary candidate with configured `max_input_tokens` lower than estimated prompt tokens is never selected for that request.
- If an eligible fallback exists in the selected tier, it is promoted when all primary candidates are over limit.
- If the selected tier has no eligible primary or fallback, routing searches higher tiers and may select an eligible higher-tier primary or fallback.
- If every configured candidate with known input limits is over limit and no unknown-limit candidate exists, routing returns a clear routing failure instead of selecting a known-over-limit model.
- Capability filtering and fallback-backoff cooldown behavior remain ordered correctly: input-limit/capability eligibility determines candidate safety, cooldown may affect availability, and cooldown fallback may be ignored only among input-limit-eligible candidates.
- Existing behavior for candidates without `max_input_tokens` remains backward compatible: unknown-limit candidates remain eligible.

## Explicit Completion Conditions

- `src/kani/router.py` no longer uses the original primary candidate list as a final fallback after input-limit filtering eliminates all candidates.
- A specific exception or existing structured routing failure path is used when no input-limit-eligible candidate exists; FastAPI proxy boundaries continue returning structured OpenAI-style errors if this failure reaches the API layer.
- Focused tests prove fallback promotion, higher-tier promotion, unknown-limit eligibility, and no unsafe primary fallback when all known candidates are over limit.
- Tests prove cooldown fallback does not reintroduce over-limit candidates when all eligible candidates are cooling down.
- OpenSpec canonical routing requirements are updated to describe authoritative input-limit fallback behavior.

## Out of Scope

- Changing token estimation semantics in `kani.compaction._estimate_tokens`.
- Requiring all model entries to declare `max_input_tokens`.
- Adding provider/model metadata discovery.
- Renaming or changing smart-proxy compaction `context_window_tokens` threshold behavior.
