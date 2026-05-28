## ADDED Requirements

### Requirement: Provider-specific reasoning control injection

Routed chat completion requests SHOULD receive provider-specific reasoning control payload fields when kani can infer an appropriate default and the client has not already provided reasoning or thinking controls.

#### Scenario: OpenAI-style reasoning injection

**Given**: a routed request selects a provider with `reasoning_style: openai`
**And**: the client request contains no explicit reasoning or thinking control field
**When**: kani proxies the request upstream
**Then**: kani SHOULD include `reasoning: {"effort": "<effort>"}` in the upstream payload
**And**: kani MUST preserve the selected actual model in `model`

#### Scenario: Anthropic-style effort injection

**Given**: a routed request selects a provider with `reasoning_style: anthropic`
**And**: the client request contains no explicit reasoning or thinking control field
**When**: kani proxies the request upstream
**Then**: kani SHOULD include `output_config.effort` in the upstream payload
**And**: kani MUST preserve unrelated `output_config` fields if present

#### Scenario: DashScope-style thinking injection

**Given**: a routed request selects a provider with `reasoning_style: dashscope`
**And**: the client request contains no explicit reasoning or thinking control field
**When**: kani proxies the request upstream
**Then**: kani SHOULD include `enable_thinking` in the upstream payload

#### Scenario: Gemini-style thinking budget injection

**Given**: a routed request selects a provider with `reasoning_style: gemini`
**And**: the client request contains no explicit reasoning or thinking control field
**When**: kani proxies the request upstream
**Then**: kani SHOULD include `generationConfig.thinkingConfig.thinkingBudget` in the upstream payload
**And**: kani MUST preserve unrelated `generationConfig` and `thinkingConfig` fields if present

#### Scenario: Reasoning injection disabled

**Given**: a routed request selects a provider with `reasoning_style: none`
**When**: kani proxies the request upstream
**Then**: kani MUST NOT add reasoning or thinking control fields for this feature

#### Scenario: Client-provided controls are preserved

**Given**: a routed request includes any of `reasoning`, `reasoning_effort`, `thinking`, `output_config.effort`, `enable_thinking`, or `generationConfig.thinkingConfig.thinkingBudget`
**When**: kani proxies the request upstream
**Then**: kani MUST NOT overwrite that client-provided reasoning or thinking control
**And**: kani MUST NOT add a second provider-specific reasoning control that conflicts with the client-provided control

#### Scenario: Pass-through requests are not modified

**Given**: `model` does not start with `kani/`
**When**: kani proxies the request to `default_provider`
**Then**: kani MUST NOT add reasoning or thinking control fields for this feature

#### Scenario: Fallback provider uses its own reasoning style

**Given**: a routed request fails on the primary candidate and retries a fallback candidate
**And**: the fallback candidate resolves to a provider with a different `reasoning_style` than the primary provider
**When**: kani builds the fallback upstream payload
**Then**: kani MUST apply the fallback provider's `reasoning_style`
**And**: kani MUST NOT reuse stale primary-provider reasoning controls that conflict with the fallback provider style
