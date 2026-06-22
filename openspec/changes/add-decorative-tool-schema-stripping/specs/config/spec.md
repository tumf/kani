## MODIFIED Requirements

### Requirement: 設定スキーマ

設定は以下の構造に従わなければならない (SHALL)。Profile tier model entries MAY include optional `max_input_tokens` metadata for routing-time input-limit candidate filtering. Configuration MUST expose a tools capability detection policy with a backward-compatible default of `declared`. Configuration MUST also expose a decorative tool schema handling policy with a backward-compatible default that preserves upstream payloads unchanged.

#### Scenario: トップレベル設定

- GIVEN 有効な YAML 設定ファイル
- WHEN 読み込みとバリデーションを行う
- THEN 以下のフィールドが利用可能である:
  - `host` (str, デフォルト: "0.0.0.0")
  - `port` (int, デフォルト: 18420)
  - `providers` (dict[str, ProviderConfig])
  - `default_provider` (str, デフォルト: "openrouter")
  - `profiles` (dict[str, ProfileConfig])
  - `default_profile` (str, デフォルト: "auto")
  - `llm_classifier` (LLMClassifierConfig | None)
  - `model_rules` (list[ModelRuleEntry])
  - `model_capabilities` (legacy list[ModelRuleEntry])

#### Scenario: decorative tool schema handling defaults to preserve

**Given** a configuration does not specify decorative tool schema handling
**When** the configuration is loaded
**Then** kani MUST use `preserve` as the decorative tool schema handling policy
**And** routed upstream payloads MUST preserve top-level `tools`, `functions`, `tool_choice`, and `function_call` fields unless another explicit policy is configured

#### Scenario: decorative tool schema stripping policy is accepted

**Given** a configuration explicitly sets decorative tool schema handling to `strip`
**When** the configuration is loaded
**Then** kani MUST preserve that policy for routed upstream payload adaptation
**And** kani MUST NOT require operators to change `model_rules` capability metadata to use the policy

#### Scenario: invalid decorative tool schema handling policy is rejected

**Given** a configuration sets decorative tool schema handling to an unsupported value
**When** the configuration is validated
**Then** kani MUST reject the configuration as invalid
**And** the invalid value MUST NOT silently fall back to either `preserve` or `strip`
