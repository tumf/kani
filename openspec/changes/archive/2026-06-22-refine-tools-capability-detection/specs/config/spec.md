## MODIFIED Requirements

### Requirement: 設定スキーマ

設定は以下の構造に従わなければならない (SHALL)。Profile tier model entries MAY include optional `max_input_tokens` metadata for routing-time input-limit candidate filtering. Configuration MUST expose a tools capability detection policy with a backward-compatible default of `declared`.

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

#### Scenario: tools capability detection policy defaults to declared

**Given** a configuration does not specify a tools capability detection policy
**When** the configuration is loaded
**Then** kani MUST use `declared` as the tools capability detection policy
**And** requests containing `tools` or `functions` declarations MUST keep requiring the `tools` capability by default

#### Scenario: active tools capability detection policy is accepted

**Given** a configuration explicitly sets the tools capability detection policy to `active`
**When** the configuration is loaded
**Then** kani MUST preserve that policy for routing-time capability detection
**And** kani MUST NOT require operators to change `model_rules` capability metadata to use the policy

#### Scenario: invalid tools capability detection policy is rejected

**Given** a configuration sets the tools capability detection policy to an unsupported value
**When** the configuration is validated
**Then** kani MUST reject the configuration as invalid
**And** the invalid value MUST NOT silently fall back to either `declared` or `active`
