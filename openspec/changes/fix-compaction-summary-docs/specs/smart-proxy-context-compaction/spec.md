## MODIFIED Requirements

### Requirement: Configurable synchronous context compaction

kani MUST allow operators to enable or disable synchronous request-time context compaction independently from other smart-proxy features. Current documentation MUST describe summary generation configuration using `summary_profile`, not the removed `summary_model` field.

#### Scenario: Documentation uses summary_profile for summary routing

**Given** an operator reads current smart-proxy compaction documentation
**When** they configure synchronous compaction summary generation
**Then** the documentation must instruct them to use `sync_compaction.summary_profile`
**And** it must explain that an empty `summary_profile` falls back through default profile routing resolution
**And** it must not instruct them to configure `sync_compaction.summary_model`
