# Proxy API

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
**And** when no messages contain `reasoning_content`, the original request body MUST be returned without copying or deep-copying message objects

#### Scenario: Sanitization performance optimization

**Given** a routed chat completion request contains messages but no message contains `reasoning_content`
**When** kani builds the upstream request payload
**Then** kani MUST NOT deep-copy or otherwise mutate the request body
