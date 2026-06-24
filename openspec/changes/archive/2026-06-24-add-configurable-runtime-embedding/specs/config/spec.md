## MODIFIED Requirements

### Requirement: 設定スキーマ

設定は以下の構造に従わなければならない (SHALL)。Profile tier model entries MAY include optional `max_input_tokens` metadata for routing-time input-limit candidate filtering. Configuration MUST expose a tools capability detection policy with a backward-compatible default of `declared`. Configuration MUST also expose a decorative tool schema handling policy with a backward-compatible default that preserves upstream payloads unchanged. Configuration MUST expose runtime embedding backend selection so operators can choose API, local, or disabled embedding behavior explicitly.

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
  - `embedding` (EmbeddingConfig | None)
  - `model_rules` (list[ModelRuleEntry])
  - `model_capabilities` (legacy list[ModelRuleEntry])

#### Scenario: embedding API mode is accepted

**Given** a configuration sets `embedding.mode` to `api`
**And** `embedding.model` is set
**And** either `embedding.provider` resolves through `providers` or direct `embedding.base_url` / environment fallback is available
**When** configuration is loaded and runtime classification requests embeddings
**Then** kani MUST use the configured API embedding model and provider/base URL
**And** kani MUST apply `embedding.timeout_seconds` to the runtime embedding call
**And** kani MUST NOT expose the resolved API key in diagnostics or logs

#### Scenario: local embedding mode is accepted

**Given** a configuration sets `embedding.mode` to `local`
**And** `embedding.local_model` is set
**When** runtime classification requests embeddings
**Then** kani MUST use the configured local embedding model identity
**And** kani MUST NOT call an external embedding API for that classification request
**And** local backend import or runtime failure MUST be surfaced as classifier unavailability that falls back safely

#### Scenario: disabled embedding mode is explicit

**Given** a configuration sets `embedding.mode` to `disabled`
**When** runtime prompt classification is requested
**Then** kani MUST skip learned classifier embedding execution
**And** routing MUST converge to the conservative default fallback
**And** diagnostics SHOULD report default-only routing due to disabled embedding

#### Scenario: invalid embedding configuration is rejected

**Given** a configuration sets an unsupported `embedding.mode`
**Or** `embedding.timeout_seconds` is less than or equal to zero
**When** configuration is validated
**Then** kani MUST reject the configuration as invalid
**And** invalid values MUST NOT silently fall back to API, local, or disabled mode
