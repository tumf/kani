## MODIFIED Requirements

### Requirement: Configurable synchronous context compaction

kani MUST use model-aware tokenization for compaction threshold evaluation when tiktoken supports the target model encoding.

#### Scenario: Token estimation uses tiktoken for known models

**Given** smart-proxy synchronous compaction is enabled
**And** the routed request specifies a model name recognized by tiktoken
**When** kani estimates token count for threshold evaluation
**Then** kani MUST use the tiktoken encoding for that model instead of the fixed character-ratio estimator

#### Scenario: Token estimation falls back for unknown models

**Given** smart-proxy synchronous compaction is enabled
**And** the routed request specifies a model name not recognized by tiktoken
**When** kani estimates token count for threshold evaluation
**Then** kani MUST fall back to `cl100k_base` encoding without error
**And** kani MUST NOT crash or skip compaction due to the unrecognized model
