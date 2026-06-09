## MODIFIED Requirements

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
