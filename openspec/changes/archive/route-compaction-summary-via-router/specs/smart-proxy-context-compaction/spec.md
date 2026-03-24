## MODIFIED Requirements

### Requirement: Configurable synchronous context compaction

kani MUST allow operators to configure which routing profile is used for summary model resolution during compaction, instead of requiring a specific model ID or hardcoded profile name.

#### Scenario: Summary model resolved via Router profile

**Given** smart-proxy synchronous compaction is enabled
**And** `summary_profile` is configured (or empty for default)
**When** kani needs to generate a compaction summary
**Then** kani MUST resolve the summary model, provider base_url, and api_key through the Router's profile/tier resolution mechanism
**And** kani MUST NOT hardcode a dependency on any specific profile name such as `compress`

#### Scenario: Empty summary_profile falls back to default_profile

**Given** smart-proxy synchronous compaction is enabled
**And** `summary_profile` is empty or unset
**When** kani resolves the summary model
**Then** kani MUST use the configured `default_profile` for model resolution

#### Scenario: Summary model resolution does not trigger scoring or routing logs

**Given** smart-proxy compaction resolves a summary model via the Router
**When** the Router resolves the model for compaction use
**Then** the Router MUST NOT run the scorer classifier
**And** the Router MUST NOT write a routing log entry for this internal resolution

## ADDED Requirements

### Requirement: Lightweight model resolution without scoring

The Router MUST provide a method to resolve a model, provider, and connection details for a given profile and tier without running prompt classification or recording routing decisions.

#### Scenario: resolve_model returns a valid RoutingDecision

**Given** a valid profile and tier exist in the configuration
**When** `Router.resolve_model(profile=..., tier=...)` is called
**Then** the Router MUST return a `RoutingDecision` with resolved model, base_url, api_key, provider, and fallbacks
**And** the Router MUST NOT invoke the scorer
**And** the Router MUST NOT call RoutingLogger
