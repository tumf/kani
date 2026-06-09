## ADDED Requirements

### Requirement: CLI output must not expose raw API keys

When the `kani` CLI serializes routing decisions or other data structures containing non-empty API key values, it MUST redact the raw key content and output a mask placeholder (e.g. `"***"`) instead. Empty API key values MUST remain unset/empty rather than being converted into a fake configured-secret marker.

#### Scenario: route command masks api_key in decision output

**Given** a valid config with a non-empty API key for the active provider
**When** `kani route "test prompt"` is executed
**Then** the JSON output must NOT contain the literal API key string
**And** the `"api_key"` field (both top-level and within fallback entries) must contain `"***"`

#### Scenario: route command preserves empty api_key values

**Given** a config where the provider API key is empty or unset
**When** `kani route "test prompt"` is executed
**Then** the JSON output must be valid and not raise any errors
**And** the corresponding `"api_key"` field must remain an empty string
