---
change_type: implementation
priority: medium
dependencies: []
references:
  - "openspec/specs/routing/spec.md:362"
  - "openspec/specs/proxy-api/spec.md:9"
  - "src/kani/proxy.py:_decide_tools_capability"
  - "src/kani/proxy.py:chat_completions"
  - "tests/test_proxy_reload.py"
---

# Add Decorative Tool Schema Stripping

**Change Type**: implementation

## Problem/Context

Kani now supports `smart_proxy.tools_capability_detection: active`, which can treat top-level `tools` or legacy `functions` declarations as decorative for routing capability detection. This lets Kani avoid forcing a tools-capable model when there is no forced or active tool use.

However, the original request payload is still forwarded upstream unchanged. If routing selects a candidate whose model or provider rejects `tools`, `functions`, `tool_choice`, or legacy `function_call` fields, the request may fail upstream even though Kani intentionally decided that tools are not required for that turn.

This proposal adds an explicit, opt-in payload adaptation layer for the already-detected decorative-tool case. It must preserve OpenAI API compatibility and client intent: Kani must never strip fields when tool use is required, forced, or active.

## Proposed Solution

Add a configurable smart-proxy payload policy that can strip decorative tool schema fields only when Kani's tools capability decision says tools are declared but not required.

Recommended minimal policy shape:

- `smart_proxy.decorative_tool_schema_handling: preserve` by default
- `smart_proxy.decorative_tool_schema_handling: strip` as opt-in

Behavior:

1. Keep the default behavior unchanged: preserve all client tool fields upstream.
2. When policy is `strip` and the tools capability decision is `declared=True`, `required=False`, remove decorative tool request fields before forwarding upstream.
3. Never strip when `required=True`, including forced `tool_choice`, forced legacy `function_call`, assistant `tool_calls`, `role=tool`, or legacy `role=function` activity.
4. Make stripping auditable in logs or route diagnostics without logging tool schema contents.
5. Apply only to routed `kani/<profile>` chat completions initially; passthrough mode should preserve the request exactly.

The implementation should reuse the existing tools capability decision helper rather than re-deriving intent independently.

## Acceptance Criteria

- Existing behavior remains unchanged unless the new stripping policy is explicitly configured.
- With stripping enabled and active tools detection classifies tool schemas as decorative, upstream receives a copy of the request without top-level `tools`, legacy `functions`, `tool_choice`, and legacy `function_call` fields.
- The client request object is not mutated in-place in a way that affects routing diagnostics, logging, retries, tests, or future middleware; payload adaptation should use a copied upstream body.
- Stripping is never applied when tools are required by forced choice or active tool history.
- Passthrough mode for non-`kani/` model names preserves original payload fields.
- Logs or debug diagnostics indicate when decorative tool schema stripping was applied without exposing schema names or contents.
- Tests cover the strip and preserve paths, forced/active safety paths, passthrough preservation, and fallback retry reuse of the adapted payload.

## Explicit Completion Conditions

The change is complete when repository evidence shows all of the following:

- `src/kani/config.py` validates the new decorative tool schema handling policy with a backward-compatible default.
- `src/kani/proxy.py` adapts only the upstream request body, not the original routing input, when stripping is enabled.
- Non-streaming and streaming routed chat completion code paths use the adapted body consistently for primary and fallback attempts.
- `/v1/route` or logs expose whether stripping would apply or did apply without revealing tool schema contents.
- Unit/integration tests in `tests/test_capability_routing.py`, `tests/test_proxy_reload.py`, `tests/test_api_keys_proxy.py`, or equivalent verify strip/preserve/safety/passthrough behavior.
- README and `config.example.yaml` document the new opt-in policy and its interaction with `tools_capability_detection: active`.
- Quality gates pass: `uv run ruff check src/`, `uv run ruff format --check src/ tests/`, `uv run pyright src/`, and relevant pytest coverage.

## Out of Scope

- Automatically stripping tool schemas for default `declared` policy.
- Stripping when the client explicitly forces a tool/function call.
- Rewriting message history or removing `tool_calls`, `role=tool`, or `role=function` messages.
- Provider-specific schema rewriting beyond removing top-level decorative fields.
- Automatically detecting client products by user-agent or headers.
- Changing model capability metadata in `model_rules`.
