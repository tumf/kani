---
change_type: implementation
priority: medium
dependencies: []
references:
  - "https://github.com/tumf/kani/issues/9"
  - "src/kani/proxy.py:_detect_required_capabilities"
  - "src/kani/config.py:SmartProxyConfig"
  - "tests/test_capability_routing.py:TestCapabilityDetection"
  - "openspec/CONSTITUTION.md"
---

# Refine Tools Capability Detection

**Change Type**: implementation

## Problem/Context

Kani currently treats the presence of `tools` or legacy `functions` in an OpenAI-compatible chat completion request as a hard `tools` capability requirement. This is safe, but too coarse for clients that attach their full tool schema to every request even when a turn is ordinary conversation and no tool call is active.

Issue #9 reports this as unnecessary up-tiering: decorative tool declarations force routing to tools-capable, often heavier models, even when the conversation never uses tools. The requested change is a capability-branching logic improvement, not an immediate source patch in this proposal.

The design must still preserve Kani's constitution:

- OpenAI API compatibility must remain stable.
- Routing decisions must be deterministic and auditable.
- Capability-required requests must fail closed.
- Explicit client intent such as forced tool use must not be weakened.

## Proposed Solution

Introduce a configurable tools capability detection policy while keeping the existing behavior as the default.

1. Add a configuration surface under smart-proxy or an equivalent top-level routing configuration for tools capability detection policy.
2. Preserve the current default policy, `declared`, where any `tools` or `functions` declaration requires the `tools` capability.
3. Add an opt-in policy, `active`, for clients that send decorative tool schemas on every request.
4. Under `active`, require the `tools` capability only when request fields or recent message history show active or explicit tool use.
5. Make the selected policy visible in routing diagnostics or logs so operators can audit why `tools` was or was not required.
6. Update docs and tests to describe both the safe default and opt-in behavior.

## Acceptance Criteria

- Existing configurations continue to treat `tools` or `functions` declarations as requiring `tools` capability unless the new opt-in policy is configured.
- With the opt-in active policy, decorative `tools` or `functions` declarations do not by themselves require the `tools` capability.
- With the opt-in active policy, explicit forced tool use still requires the `tools` capability.
- With the opt-in active policy, active tool state in recent message history still requires the `tools` capability.
- Requests that truly require `tools` still fail closed when no candidate declares the capability.
- Routing diagnostics/logging make the capability decision auditable.
- README and relevant configuration/spec documentation explain the trade-off and default behavior.

## Explicit Completion Conditions

The change is complete when repository evidence shows all of the following:

- `src/kani/config.py` exposes and validates the tools capability detection policy with a backward-compatible default.
- `src/kani/proxy.py` separates raw tool declaration detection from the policy-based decision that adds `tools` to required capabilities.
- `tool_choice` / legacy function choice semantics are handled so forced tool invocation cannot be routed to a model without tool support.
- Tests in `tests/test_capability_routing.py` or equivalent cover default declared behavior, opt-in active behavior, forced tool use, active tool history, and resolved historical tool activity before the latest user turn.
- Router/proxy tests prove capability fail-closed behavior remains intact for tool-required requests.
- `README.md` and/or configuration documentation describe the new policy, default, and intended OpenCode-style use case.
- Quality gates pass: `uv run ruff check src/`, `uv run ruff format --check src/ tests/`, `uv run pyright src/`, and relevant pytest coverage.

## Out of Scope

- Automatically detecting specific clients such as OpenCode, Cursor, or Continue by headers or user agents.
- Pruning or rewriting tool schemas before forwarding upstream.
- Changing model capability metadata semantics in `model_rules`.
- Changing default behavior away from fail-closed declared-tool detection.
- Implementing a heuristic semantic classifier for whether a prompt is likely to call tools.
