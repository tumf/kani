---
change_type: spec-only
priority: low
dependencies: []
references:
  - README.md
  - config.example.yaml
  - src/kani/config.py
  - src/kani/proxy.py
  - openspec/specs/smart-proxy-context-compaction/spec.md
---

# Fix smart-proxy compaction summary profile documentation

**Change Type**: spec-only

## Problem

README smart-proxy compaction docs still mention `summary_model`, but the current implementation and archived change `route-compaction-summary-via-router` replaced `SyncCompactionConfig.summary_model` with `summary_profile`.

Current implementation evidence:

- `src/kani/config.py` defines `summary_profile` on synchronous compaction config.
- `src/kani/proxy.py` resolves summary generation through `router.resolve_model(profile=sync_cfg.summary_profile or None, ...)`.
- `config.example.yaml` already documents `summary_profile`.

This doc drift can lead operators to configure an unsupported field.

## Proposed Solution

Update the README smart-proxy compaction section to document `summary_profile` and its actual fallback behavior.

Spec delta clarifies that docs must match the current behavior:

- Operators configure a routing profile for summary generation via `summary_profile`.
- Empty `summary_profile` uses the default routing profile, not an implicit raw model string.
- `summary_model` is not the documented configuration surface.

## Acceptance Criteria

- README config snippet uses `summary_profile`, not `summary_model`.
- README prose explains the actual fallback behavior: empty `summary_profile` falls back to `default_profile` through router model resolution.
- Documentation remains consistent with `config.example.yaml` and `src/kani/config.py`.
- No runtime behavior changes are introduced.

## Explicit Completion Conditions

- Edit README lines around the smart-proxy compaction configuration example and prose to remove `summary_model` references.
- Confirm `rg "summary_model" README.md config.example.yaml src/kani` returns no active source/example references except archived changes or internal function parameter names where still intentionally named.
- Run `uv run ruff format --check src/ tests/` or skip if only README changes are made; no Python behavior changes are expected.

## Out of Scope

- Changing compaction runtime behavior.
- Adding migration support for legacy `summary_model` config.
- Editing archived OpenSpec changes.
