## MODIFIED Requirements

### Requirement: Input-limit-aware candidate selection

Routing MUST avoid selecting model candidates whose configured input-token limit is smaller than the estimated request prompt tokens. The input-limit filter is authoritative for candidates that declare a limit: once a known-over-limit candidate is filtered out, routing MUST NOT reintroduce that candidate through a final default or upstream fallback path.

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

#### Scenario: No unsafe primary fallback when every known candidate is too small

**Given**: every configured candidate with a known `max_input_tokens` is lower than the estimated prompt tokens
**And**: no unknown-limit candidate is available
**When**: routing selects a model for the request
**Then**: kani MUST fail routing with a clear no-input-limit-eligible-candidate error
**And**: kani MUST NOT select any known-over-limit candidate as a final fallback

#### Scenario: Cooldown applies only after input-limit filtering

**Given**: multiple candidates fit the estimated prompt tokens
**And**: one fitted candidate is in fallback-backoff cooldown
**When**: routing selects a model for the request
**Then**: kani MUST skip the cooled candidate when another fitted candidate is available
**And**: if cooldown must be ignored because every fitted candidate is cooling down, kani MUST choose only from candidates that still fit the estimated prompt tokens
