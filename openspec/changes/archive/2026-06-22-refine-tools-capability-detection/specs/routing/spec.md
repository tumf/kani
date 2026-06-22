## ADDED Requirements

### Requirement: Tools capability detection policy

Kani MUST determine whether a routed request requires the `tools` capability using the configured tools capability detection policy. The default policy MUST preserve declared-tool fail-closed behavior, while the opt-in active policy MAY treat decorative tool declarations as non-requirements when explicit or active tool use is absent.

#### Scenario: declared policy treats tool declarations as required

**Given** the tools capability detection policy is `declared`
**And** a routed chat completion request includes a `tools` or legacy `functions` field
**When** kani detects required capabilities
**Then** kani MUST include `tools` in the required capability set

#### Scenario: active policy ignores decorative tool declarations

**Given** the tools capability detection policy is `active`
**And** a routed chat completion request includes a `tools` or legacy `functions` field
**And** the request does not force tool use
**And** there is no assistant `tool_calls`, legacy assistant `function_call`, `role="tool"`, or legacy `role="function"` message after the latest user message
**When** kani detects required capabilities
**Then** kani MUST NOT include `tools` solely because tool declarations are present

#### Scenario: active policy preserves forced tool use

**Given** the tools capability detection policy is `active`
**And** a routed chat completion request includes a `tools` or legacy `functions` field
**And** the request uses `tool_choice`, legacy `function_call`, or another OpenAI-compatible request field to force a tool or function call
**When** kani detects required capabilities
**Then** kani MUST include `tools` in the required capability set

#### Scenario: active policy preserves active tool history

**Given** the tools capability detection policy is `active`
**And** a routed chat completion request includes a `tools` or legacy `functions` field
**And** after the latest user message, the message history contains assistant `tool_calls`, legacy assistant `function_call`, `role="tool"`, or legacy `role="function"`
**When** kani detects required capabilities
**Then** kani MUST include `tools` in the required capability set

#### Scenario: active policy ignores resolved historical tool activity

**Given** the tools capability detection policy is `active`
**And** a routed chat completion request includes a `tools` or legacy `functions` field
**And** tool activity exists only before the latest user message
**When** kani detects required capabilities
**Then** kani MUST NOT include `tools` because of that resolved historical activity

#### Scenario: tool-required requests still fail closed

**Given** a routed request requires the `tools` capability after applying the configured tools capability detection policy
**And** no configured model candidate declares the `tools` capability
**When** routing evaluates candidates
**Then** kani MUST fail routing with a clear capability-not-satisfied error
**And** kani MUST NOT select a candidate that lacks `tools`

#### Scenario: tools capability decision is auditable

**Given** a routed request includes a `tools` or legacy `functions` declaration
**When** kani detects required capabilities and routes the request
**Then** routing diagnostics or logs SHOULD indicate the configured tools detection policy and whether declarations, forced tool choice, or active tool history contributed to the final `tools` capability decision
**And** diagnostics MUST NOT log full tool schema contents by default
