---
change_type: spec-only
priority: medium
dependencies: []
references:
  - https://github.com/tumf/kani/issues/5
  - README.md
  - config.yaml
  - openspec/specs/config/spec.md
  - openspec/specs/routing/spec.md
  - openspec/specs/smart-proxy-context-compaction/spec.md
---

# Audit Routing Docs

**Change Type**: spec-only

## Problem / Context

The field report identified documentation/spec drift around model rule configuration, legacy model capability aliases, tier-level provider overrides, literal model ID behavior, and smart-proxy session behavior. Current code confirms that `model_rules` is the primary model metadata surface, `model_capabilities` is a legacy alias, capability-required requests fail closed when no configured candidate declares required capabilities, and compaction no longer derives session IDs when the explicit header is absent.

This proposal is documentation/specification alignment only. It does not implement runtime behavior.

## Proposed Solution

Update canonical spec deltas and user-facing documentation tasks so they accurately describe current intended behavior:

- `model_rules` is the primary model metadata mechanism.
- `model_capabilities` is a legacy alias that is normalized into `model_rules` when `model_rules` is unset.
- Required capability filtering fails closed when no configured candidate declares the required capability set.
- Provider resolution precedence is model-entry provider, then tier-level provider, then `default_provider`.
- Configured model IDs are sent literally to the selected provider; kani does not parse `provider/model` syntax except as a literal provider model ID.
- Without `X-Kani-Session-Id`, compaction uses no derived session ID; inline compaction may run but cache reuse, persistence, incremental summarization, and background precompaction are unavailable.

## Acceptance Criteria

1. Canonical config requirements describe `model_rules` as the primary model metadata mechanism and `model_capabilities` as a legacy compatibility alias.
2. Routing requirements clearly document provider resolution precedence and literal model ID behavior.
3. Smart-proxy session requirements state explicit-header behavior and no-header behavior without stale derived-session claims.
4. Capability routing documentation/spec text states that requests requiring capabilities fail closed when no configured candidate declares the required capabilities.
5. Any discovered contradiction that requires code changes is not hidden in docs; it is tracked as a separate implementation issue/proposal.

## Explicit Completion Conditions

- Spec deltas under this change define the required canonical documentation/spec outcomes.
- README/config example updates are represented as tasks for this docs/spec-only change application, but no runtime code changes are required by this proposal.
- Strict OpenSpec validation passes for this change.

## Out of Scope

- Runtime behavior changes.
- Adding new routing capabilities.
- Changing provider resolution semantics.
- Fixing compaction behavior beyond documenting or tracking any discovered mismatch.
