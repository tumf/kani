## ADDED Requirements

### Requirement: Incremental hierarchical summarization

kani MUST support incremental summarization that reuses prior summaries instead of re-summarizing the entire middle region from scratch on every compaction cycle.

#### Scenario: Delta-only summarization when prior summary exists

**Given** smart-proxy synchronous compaction is enabled
**And** a ready summary exists for the session covering the first K messages of the middle region
**And** new messages have been added beyond the prior summary's coverage
**When** kani compacts the message history
**Then** kani MUST summarize only the new unsummarized messages (the delta)
**And** kani MUST merge the prior summary with the delta summary

#### Scenario: Full summarization when no prior summary exists

**Given** smart-proxy synchronous compaction is enabled
**And** no prior summary exists for the current session
**When** kani compacts the message history
**Then** kani MUST summarize the entire middle region (identical to current single-pass behavior)

#### Scenario: Merge strategy selection by combined size

**Given** a prior summary and a new delta summary have been produced
**When** kani merges the two summaries
**Then** kani MUST concatenate them without an additional LLM call if their combined token count is below `merge_threshold`
**And** kani MUST produce a condensed merge via an LLM call if their combined token count meets or exceeds `merge_threshold`

#### Scenario: Fallback to full summarization on snapshot mismatch

**Given** a prior summary exists for the session
**And** the current message snapshot hash does not match the stored lineage
**When** kani attempts incremental compaction
**Then** kani MUST fall back to full single-pass summarization
**And** kani MUST NOT use the mismatched prior summary
