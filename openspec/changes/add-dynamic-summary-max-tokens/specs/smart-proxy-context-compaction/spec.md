## MODIFIED Requirements

### Requirement: Configurable synchronous context compaction

kani MUST compute the summary generation token budget dynamically based on the size of the middle message region being compacted.

#### Scenario: Summary token budget scales with middle region size

**Given** smart-proxy synchronous compaction is enabled
**And** the middle region of the conversation contains N estimated tokens
**When** kani generates a handoff summary for the middle region
**Then** kani MUST set the summary `max_tokens` to `clamp(N * summary_ratio, min_summary_tokens, max_summary_tokens)` using operator-configurable ratio, floor, and ceiling values

#### Scenario: Summary token budget respects configured floor

**Given** smart-proxy synchronous compaction is enabled
**And** the middle region is very short (N * summary_ratio < min_summary_tokens)
**When** kani generates a handoff summary
**Then** kani MUST use `min_summary_tokens` as the token budget floor

#### Scenario: Summary token budget respects configured ceiling

**Given** smart-proxy synchronous compaction is enabled
**And** the middle region is very long (N * summary_ratio > max_summary_tokens)
**When** kani generates a handoff summary
**Then** kani MUST use `max_summary_tokens` as the token budget ceiling
