# Design: Tools Capability Detection Policy

## Current Behavior

`_detect_required_capabilities()` currently adds `tools` whenever the request body contains `tools` or legacy `functions`. This is conservative and compatible with OpenAI-style requests because a model that cannot call tools may be incapable of satisfying a request where the client provided tools.

## Proposed Policy Model

Add a small enum-like policy, tentatively named `tools_capability_detection`, with two modes:

- `declared`: default. Any `tools` or `functions` declaration requires the `tools` capability.
- `active`: opt-in. Tool declarations are treated as potentially decorative unless the request indicates explicit or currently active tool usage.

The exact config location can be chosen during implementation, but it should live near existing smart-proxy/routing behavior so operators understand it affects routing safety. A likely location is `smart_proxy.tools_capability_detection` or `smart_proxy.capability_detection.tools` if a nested capability-detection config is preferred.

## Active Policy Semantics

Under `active`, the request requires the `tools` capability if any of these are true:

1. The request explicitly forces tool use:
   - `tool_choice` is `"required"`.
   - `tool_choice` is an object selecting a specific function/tool.
   - legacy `function_call` is an object selecting a function or otherwise forces function use.
   - legacy `function_call` is a string value that forces use, if such input is accepted by the current request parser.
2. The latest unresolved assistant/tool exchange after the most recent user message shows active tool state:
   - assistant message contains non-empty `tool_calls`.
   - assistant message contains legacy `function_call`.
   - message role is `tool`.
   - message role is legacy `function`.
3. The request shape otherwise unambiguously requires model-side tool call output support.

Under `active`, the request does not require `tools` if the only evidence is a decorative `tools` or `functions` declaration and the latest user turn has no active tool state.

## Why Opt-In

Making `active` the default would risk violating client intent. A request may include tools because the current user turn expects the model to decide whether to call one. If Kani routes that request to a non-tools model, the model cannot satisfy that intent even if no tool call exists yet in message history. Keeping `declared` as default preserves fail-closed safety and backward compatibility.

## Auditing

Routing diagnostics should expose enough information to reconstruct the decision without logging full tool schemas. Suitable audit values include:

- configured tools detection policy
- whether tool declarations were present
- whether forced tool choice was detected
- whether active tool history was detected
- final required capability set

This can be added to routing logs or `X-Kani-Signals`-adjacent diagnostics if practical without changing stable response semantics unexpectedly.

## Alternatives Considered

### Replace declared detection globally with active detection

Rejected. This reduces cost for schema-heavy clients but can route genuinely tool-capable turns to models that cannot emit tool calls.

### Infer intent from natural language prompts

Rejected. The constitution forbids untracked heuristic semantic classification paths for runtime routing, and prompt-intent guessing would be less deterministic than request-shape checks.

### Detect client type automatically

Rejected for this proposal. User-agent/header detection is brittle and creates hidden behavior differences. Operators should opt in explicitly.
