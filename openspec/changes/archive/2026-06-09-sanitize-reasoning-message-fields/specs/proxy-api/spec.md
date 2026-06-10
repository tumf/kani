## ADDED Requirements

### Requirement: Reasoning message-field compatibility for routed requests

For routed chat completion requests, kani MUST adapt explicitly covered message-level reasoning metadata fields, starting with `messages[].reasoning_content`, to the selected upstream provider/model before proxying the request.

#### Scenario: Unsupported reasoning_content is stripped for primary upstream

**Given** a routed chat completion request contains `messages[].reasoning_content`
**And** the selected primary model/provider does not explicitly declare support via the repo-local compatibility flag defined by this change
**When** kani builds the upstream request payload
**Then** kani MUST remove `reasoning_content` from messages before sending the request upstream
**And** kani MUST preserve ordinary message `role` and `content` fields

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
