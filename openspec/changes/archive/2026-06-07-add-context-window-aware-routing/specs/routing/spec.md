## ADDED Requirements

### Requirement: Context-window-aware candidate selection

Routing MUST avoid selecting model candidates whose configured context window is smaller than the estimated request prompt tokens.

#### Scenario: Too-small primary is skipped

**Given**: A profile tier has primary candidates `small` and `large`
**And**: `small` has `context_window_tokens` lower than the estimated prompt tokens
**And**: `large` has `context_window_tokens` greater than or equal to the estimated prompt tokens
**When**: routing selects a model for the request
**Then**: kani MUST NOT select `small`
**And**: kani MAY select `large` if it satisfies the other routing requirements

#### Scenario: Unknown context window remains eligible

**Given**: A model candidate does not declare `context_window_tokens`
**When**: routing evaluates context-window eligibility
**Then**: kani MUST keep the candidate eligible for backward compatibility

#### Scenario: Capability filtering remains mandatory

**Given**: A long-context candidate has enough `context_window_tokens`
**And**: the request requires a capability that candidate does not provide
**When**: routing evaluates candidates
**Then**: kani MUST NOT select that candidate

#### Scenario: Fallback or higher tier can satisfy long context

**Given**: all eligible primary candidates in the selected tier are too small
**And**: a fallback or higher-tier candidate has enough `context_window_tokens`
**When**: routing selects a model for the request
**Then**: kani MUST consider the fallback or higher-tier candidate using the same capability and context-window checks

#### Scenario: Cooldown applies after context filtering

**Given**: multiple candidates fit the estimated prompt tokens
**And**: one fitted candidate is in fallback-backoff cooldown
**When**: routing selects a model for the request
**Then**: kani MUST skip the cooled candidate when another fitted candidate is available
