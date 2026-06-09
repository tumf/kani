## MODIFIED Requirements

### Requirement: Model metadata documentation

`model_rules` is the primary configuration surface for prefix-based model metadata. The `supports_reasoning_content` field in each entry uses the same prefix/provider scoring precedence as `reasoning_style`: provider-matching rules always take priority over provider-agnostic rules, even when the provider-agnostic rule has a longer prefix.

#### Scenario: Model rule precedence is documented

**Given** an operator reads `model_rules` documentation or the relevant function docstring
**When** kani resolves `supports_reasoning_content`
**Then** the precedence (provider-match > prefix length) is clearly described so the operator can configure rules with confidence
