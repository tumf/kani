# Design: Decorative Tool Schema Stripping

## Relationship to Tools Capability Detection

This proposal depends on the existing tools capability decision semantics:

- `declared=True` means the request contains top-level `tools` or legacy `functions` declarations.
- `required=True` means Kani must route only to tools-capable candidates.
- `required=False` with `declared=True` is the only safe candidate state for decorative stripping.

Stripping must not introduce a second independent interpretation of tool intent. The payload adaptation should consume the already-computed `ToolsCapabilityDecision` or an equivalent single-source decision object.

## Policy Model

Add a separate policy from capability detection:

- `preserve` (default): forward tool-related request fields unchanged.
- `strip` (opt-in): when the existing decision says tool schemas are decorative, remove top-level tool schema/control fields from the upstream payload.

Keeping this separate from `tools_capability_detection` lets operators choose combinations explicitly:

- `declared + preserve`: current safest default.
- `active + preserve`: route as if schemas may be decorative, but preserve the original payload.
- `active + strip`: route and forward as a no-tool turn when schemas are decorative.

If an operator configures `declared + strip`, no stripping should normally occur because declared policy marks tool declarations as required. This avoids surprising behavior.

## Fields to Strip

When stripping applies, remove only top-level request fields that are decorative tool schema/control declarations:

- `tools`
- `functions`
- `tool_choice`
- `function_call`

Do not remove message history fields, because message history is conversational state and removing it would change the semantic content of the request. If message history contains active tool state, stripping must not apply in the first place.

## Copying and Retry Semantics

The original request body should remain available for routing, diagnostics, and audit logs. The upstream body should be a shallow copy with selected top-level fields removed. The same adapted body must be used consistently for the selected primary and any fallback attempts in the same request.

## Observability

Diagnostics should expose whether stripping was considered and applied without logging schema contents. Suitable fields include:

- configured decorative tool schema handling policy
- whether declarations were present
- whether the tools decision required tools
- whether stripping was applied
- stripped field names only, not schema contents

## Safety Rationale

The feature is opt-in because removing request fields changes the payload sent upstream. It is safe only when Kani has already determined the declarations are decorative under the active tools capability policy and there is no forced or active tool use.
