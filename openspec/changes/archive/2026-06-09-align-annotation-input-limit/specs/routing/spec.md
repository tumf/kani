## ADDED Requirements

### Requirement: Offline annotation input limit parity

Offline feature annotation MUST use the same default maximum classification text length as runtime routing classification.

#### Scenario: Annotation prompt is bounded at runtime classification length

**Given** an offline annotation prompt longer than the runtime classification input maximum
**When** kani sends it to the LLM feature annotator
**Then** the prompt content sent to the annotator MUST be truncated to the runtime classification input maximum
**And** it MUST NOT exceed that maximum

#### Scenario: Annotation prompt is not truncated at the old shorter limit

**Given** an offline annotation prompt longer than 2000 characters but no longer than the runtime classification input maximum
**When** kani sends it to the LLM feature annotator
**Then** content beyond the 2000th character MUST remain available to the annotator
