## MODIFIED Requirements

### Requirement: Input-limit-aware candidate selection

Routing MUST avoid selecting model candidates whose configured input-token limit is smaller than the estimated request prompt tokens. The per-model routing metadata for this behavior is named `max_input_tokens`.

#### Scenario: Too-small primary is skipped

**Given**: A profile tier has primary candidates `small` and `large`
**And**: `small` has `max_input_tokens` lower than the estimated prompt tokens
**And**: `large` has `max_input_tokens` greater than or equal to the estimated prompt tokens
**When**: routing selects a model for the request
**Then**: kani MUST NOT select `small`
**And**: kani MAY select `large` if it satisfies the other routing requirements

#### Scenario: Unknown input limit remains eligible

**Given**: A model candidate does not declare `max_input_tokens`
**When**: routing evaluates input-limit eligibility
**Then**: kani MUST keep the candidate eligible for backward compatibility

#### Scenario: Capability filtering remains mandatory

**Given**: A candidate has enough `max_input_tokens`
**And**: the request requires a capability that candidate does not provide
**When**: routing evaluates candidates
**Then**: kani MUST NOT select that candidate

#### Scenario: Fallback or higher tier can satisfy long input

**Given**: all eligible primary candidates in the selected tier are too small
**And**: a fallback or higher-tier candidate has enough `max_input_tokens`
**When**: routing selects a model for the request
**Then**: kani MUST consider the fallback or higher-tier candidate using the same capability and input-limit checks

#### Scenario: Cooldown applies after input-limit filtering

**Given**: multiple candidates fit the estimated prompt tokens
**And**: one fitted candidate is in fallback-backoff cooldown
**When**: routing selects a model for the request
**Then**: kani MUST skip the cooled candidate when another fitted candidate is available

#### Scenario: Smart-proxy compaction context_window_tokens remains separate

**Given**: `smart_proxy.context_compaction.context_window_tokens` is configured
**When**: routing model candidate eligibility is evaluated
**Then**: that compaction setting MUST NOT be treated as per-model `max_input_tokens`
**And**: this change MUST NOT rename or alter smart-proxy compaction threshold semantics
