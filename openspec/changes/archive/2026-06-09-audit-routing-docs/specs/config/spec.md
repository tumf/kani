## ADDED Requirements

### Requirement: Model metadata documentation

The configuration specification and user-facing documentation MUST identify `model_rules` as the primary model metadata mechanism and describe `model_capabilities` as a legacy compatibility alias.

#### Scenario: Primary model metadata field is documented

**Given** an operator reads kani configuration documentation
**When** the documentation describes model capabilities, reasoning metadata, or model rule prefix matching
**Then** it MUST present `model_rules` as the primary configuration field
**And** it MUST state that legacy `model_capabilities` is normalized into `model_rules` only when `model_rules` is unset
**And** it MUST state that configuring both `model_rules` and `model_capabilities` is invalid

#### Scenario: Missing metadata behavior is documented

**Given** no model metadata rules are configured
**When** a request requires detected capabilities such as tools, vision, or JSON mode
**Then** documentation MUST state that capability filtering fails closed because no configured candidate declares the required capability set
**And** documentation MUST state that operators need matching `model_rules` metadata for capability-required requests to route successfully
