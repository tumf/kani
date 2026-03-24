## MODIFIED Requirements

### Requirement: Switchable session and telemetry controls

kani MUST expose switchable controls and operator-visible telemetry for smart-proxy context reduction behavior. Session identity MUST only be resolved from an explicit client header; kani MUST NOT derive session identity from message content.

#### Scenario: Explicit session header is used

**Given** a client sends the configured session header
**When** kani resolves session identity for smart-proxy compaction
**Then** kani MUST use the explicit header value as the session ID
**And** kani MUST expose the resolution mode as "explicit"

#### Scenario: No session header is provided

**Given** a client does not send the configured session header
**When** kani resolves session identity for smart-proxy compaction
**Then** kani MUST resolve session ID as None with mode "none"
**And** kani MUST NOT derive a session ID from message content or model name
**And** kani MUST omit the session identity response header

#### Scenario: Sync compaction works without session identity

**Given** smart-proxy synchronous compaction is enabled
**And** no session header is provided
**And** a routed request exceeds the configured compaction threshold
**When** kani processes the request
**Then** kani MUST generate and apply an inline summary identically to session-present requests
**And** kani MUST NOT persist the generated summary for future reuse
**And** kani MUST NOT attempt cache lookup or incremental summarization

#### Scenario: Cache and background features require explicit session

**Given** background precompaction is enabled
**And** no session header is provided
**When** kani processes a request that crosses the precompaction trigger threshold
**Then** kani MUST NOT queue a background summary job
**And** kani MUST NOT persist session state or snapshot data

#### Scenario: Compaction failures do not break proxying

**Given** smart-proxy compaction is enabled
**And** summary generation, persistence, or cache lookup fails
**When** kani handles the request
**Then** kani MUST continue proxying the request without returning a compaction-specific failure to the client
**And** kani MUST record the failure for operators through logs or metrics
