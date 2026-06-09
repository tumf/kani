## Requirements

### Requirement: Configurable synchronous context compaction

kani MUST allow operators to enable or disable synchronous request-time context compaction independently from other smart-proxy features. Current documentation MUST describe summary generation configuration using `summary_profile`, not the removed `summary_model` field.

#### Scenario: Documentation uses summary_profile for summary routing

**Given** an operator reads current smart-proxy compaction documentation
**When** they configure synchronous compaction summary generation
**Then** the documentation must instruct them to use `sync_compaction.summary_profile`
**And** it must explain that an empty `summary_profile` falls back through default profile routing resolution
**And** it must not instruct them to configure `sync_compaction.summary_model`

### Requirement: Session-aware background precompaction

kani MUST support session-aware background precompaction that can be enabled or disabled independently from synchronous compaction.

#### Scenario: Background summary is queued after threshold crossing

**Given** background precompaction is enabled
**And** kani can resolve a stable session identifier for a routed conversation
**And** the session crosses the configured precompaction trigger threshold
**When** kani finishes proxying the request and records usage
**Then** kani MUST persist the current session snapshot and enqueue or refresh a background summary job for that snapshot
**And** kani MUST avoid duplicating an equivalent in-flight job for the same session snapshot

#### Scenario: Ready summary is reused on a later request

**Given** background precompaction is enabled
**And** a ready summary exists for the current session snapshot
**When** a later routed request for the same session arrives
**Then** kani MUST be able to reuse the cached summary instead of recomputing it inline
**And** kani MUST surface that a cached compaction artifact was used

### Requirement: Switchable session and telemetry controls

kani MUST expose switchable controls and operator-visible telemetry for smart-proxy context reduction behavior. Documentation and specs MUST match the current intended session identity behavior: explicit session headers produce stable session IDs, while no-header requests do not use derived session IDs.

#### Scenario: Explicit session header is preferred

**Given** a client sends the configured session header
**When** kani resolves session identity for smart-proxy compaction
**Then** kani MUST use the explicit header value as the stable session identifier
**And** kani MUST make the resolution mode observable for operators

#### Scenario: No-header requests use no derived session

**Given** a client does not send the configured session header
**When** kani resolves session identity for smart-proxy compaction
**Then** kani MUST NOT derive a synthetic session ID from model or message content
**And** kani MUST treat the request as having no session ID

#### Scenario: No-header compaction has no persistent session features

**Given** smart-proxy compaction is enabled
**And** a client does not send the configured session header
**When** kani evaluates compaction behavior
**Then** synchronous inline compaction MAY still run when the request exceeds the configured threshold
**And** cached summary reuse, session persistence, incremental summarization, and background precompaction MUST NOT run because no session ID is available
