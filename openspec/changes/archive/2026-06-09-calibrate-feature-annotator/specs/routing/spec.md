## ADDED Requirements

### Requirement: Offline feature annotator calibration

The offline feature annotator MUST provide semantic calibration guidance for every distilled routing semantic dimension when asking an LLM to label prompts.

#### Scenario: Annotator prompt includes dimension definitions

**Given** kani prepares an offline annotation request
**When** `LLMFeatureAnnotator` builds the annotator prompt
**Then** the prompt MUST include `low`, `medium`, and `high` calibration guidance for every semantic dimension
**And** the prompt MUST still require a JSON object containing exactly the semantic dimension keys

#### Scenario: Annotation parser remains strict

**Given** an annotator response omits a required dimension or returns a label outside `low`, `medium`, and `high`
**When** kani parses the annotation response
**Then** kani MUST reject that annotation result
**And** kani MUST NOT silently coerce unknown labels into valid labels
