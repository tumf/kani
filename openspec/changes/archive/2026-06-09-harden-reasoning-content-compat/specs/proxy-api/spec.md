## MODIFIED Requirements

### Requirement: Reasoning message-field compatibility for routed requests

For routed chat completion requests, kani MUST adapt explicitly covered message-level reasoning metadata fields, starting with `messages[].reasoning_content`, to the selected upstream provider/model before proxying the request. Compatibility lookup MUST be explicit and fail closed when neither a model rule nor provider config declares support. Model-rule precedence MUST be documented as provider-match first, then prefix specificity, matching the current reasoning-style precedence model.

#### Scenario: Unsupported reasoning_content is stripped for primary upstream

**Given** a routed chat completion request contains `messages[].reasoning_content`
**And** the selected primary model/provider does not explicitly declare support via the repo-local compatibility flag defined by this change
**When** kani builds the upstream request payload
**Then** kani MUST remove `reasoning_content` from messages before sending the request upstream
**And** kani MUST preserve ordinary message `role` and `content` fields
**And** the sanitized messages MUST NOT alias the original request message dictionaries

#### Scenario: Fallback upstream uses fallback compatibility rules

**Given** a routed chat completion request retries a fallback model/provider after primary failure
**And** the fallback model/provider does not explicitly declare support for `messages[].reasoning_content` via the repo-local compatibility flag defined by this change
**When** kani builds the fallback upstream request payload
**Then** kani MUST remove `reasoning_content` according to the fallback model/provider compatibility rules
**And** kani MUST NOT reuse stale primary-provider compatibility assumptions

#### Scenario: Explicitly supported reasoning_content is preserved

**Given** a selected model/provider explicitly declares support for `messages[].reasoning_content` via the repo-local compatibility flag defined by this change
**When** kani builds the upstream request payload
**Then** kani MUST preserve `reasoning_content` in messages

#### Scenario: Pass-through requests are unchanged

**Given** a chat completion request uses a model that does not start with `kani/`
**When** kani proxies the request to the default provider
**Then** kani MUST NOT apply routed-request reasoning message-field sanitization for this feature

#### Scenario: reasoning_content does not force tier escalation

**Given** a conversation history contains `messages[].reasoning_content`
**And** the current user message is otherwise simple
**When** kani classifies the request for routing
**Then** kani MUST classify based on prompt/content difficulty
**And** kani MUST NOT force a higher tier solely because the metadata field exists

#### Scenario: Provider-specific wildcard rule precedence is explicit

**Given** `model_rules` contains a provider-specific wildcard rule for provider `dummy`
**And** `model_rules` also contains a longer provider-agnostic prefix rule for the selected model
**When** kani resolves `supports_reasoning_content` for provider `dummy`
**Then** kani MUST use the provider-specific wildcard rule before the provider-agnostic specific-prefix rule
**And** this precedence MUST be covered by tests or documentation so operators do not assume longest-prefix-only matching

#### Scenario: Unknown provider fail-closed is observable

**Given** no matching `model_rules` entry declares `supports_reasoning_content`
**And** the selected provider is absent from `providers`
**When** kani resolves reasoning-content support
**Then** kani MUST return unsupported and remove `reasoning_content` for routed requests
**And** kani SHOULD emit an operator-visible warning identifying the unknown provider
