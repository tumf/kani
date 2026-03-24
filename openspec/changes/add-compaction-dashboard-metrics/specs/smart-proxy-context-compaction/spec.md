## MODIFIED Requirements

### Requirement: Switchable session and telemetry controls

kani MUST expose switchable controls and operator-visible telemetry for smart-proxy context reduction behavior, **including dashboard-integrated compaction metrics**.

#### Scenario: Compaction metrics are recorded in execution analytics

**Given** smart-proxy context compaction is enabled
**And** a routed request is processed
**When** kani records the execution event for the request
**Then** kani MUST include the compaction outcome mode, tokens saved, and original token estimate in the execution analytics record
**And** kani MUST include the session identifier in the execution analytics record

#### Scenario: Dashboard surfaces compaction summary metrics

**Given** execution analytics contain compaction records
**When** an operator accesses the dashboard
**Then** the dashboard MUST display per-window summaries of compacted request count and total tokens saved
**And** the daily trend rollup MUST include compacted request count and tokens saved per day
**And** the dashboard stats JSON API MUST include the same compaction aggregates

#### Scenario: Compaction log includes token counts for reduction analysis

**Given** smart-proxy context compaction is enabled
**And** a compaction attempt occurs (inline, cached, or skipped)
**When** kani logs the compaction outcome
**Then** the structured log MUST include the original token estimate and the compacted token count in addition to saved tokens
