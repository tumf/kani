## MODIFIED Requirements

### Requirement: 設定スキーマ

設定は以下の構造に従わなければならない (SHALL)。Profile tier model entries MAY include optional `max_input_tokens` metadata for routing-time input-limit candidate filtering.

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

#### Scenario: プロバイダ設定

- GIVEN providers セクション内のエントリ
- WHEN バリデーションを行う
- THEN 各プロバイダは `name`, `base_url` を含む
- AND `api_key` は `${ENV_VAR}` 構文を使用可能 (デフォルト: 空文字列)
- AND `reasoning_style` は `openai`, `anthropic`, `dashscope`, `gemini`, `none` のいずれかである
- AND `reasoning_style` が省略された場合は `openai` として扱われる

#### Scenario: 不正な reasoning_style

- GIVEN providers セクション内のエントリに未知の `reasoning_style` が設定されている
- WHEN 設定を検証する
- THEN システムはその設定を不正として拒否する

#### Scenario: プロファイル設定

- GIVEN profiles セクション内のエントリ
- WHEN バリデーションを行う
- THEN 各プロファイルは `tiers` ディクショナリを含む
- AND 各ティアは `primary` モデルと任意の `fallback` リストを含む
- AND `primary` と `fallback` の各エントリは文字列またはモデル名+任意のプロバイダ名+任意の `max_input_tokens` を含むオブジェクトである

#### Scenario: max_input_tokens を含むモデルエントリ

- GIVEN tier 設定の `primary` または `fallback` に `{model, provider, max_input_tokens}` オブジェクトがある
- WHEN 設定を読み込む
- THEN システムは `max_input_tokens` をそのモデル候補の最大入力トークン数として保持する
- AND `max_input_tokens` は正の整数でなければならない
- AND `provider` が未指定の場合は既存の provider 解決優先順位を維持する

#### Scenario: 文字列モデルエントリの後方互換

- GIVEN tier 設定の `primary` または `fallback` が文字列モデル ID である
- WHEN 設定を読み込む
- THEN システムは従来通りその候補を受理する
- AND input limit は未指定として扱う

#### Scenario: max_input_tokens 未指定のオブジェクトエントリ

- GIVEN tier 設定の `primary` または `fallback` に `{model, provider}` オブジェクトがある
- WHEN 設定を読み込む
- THEN システムは従来通りその候補を受理する
- AND input limit は未指定として扱う

#### Scenario: legacy context_window_tokens is not silently ignored

- GIVEN tier 設定のモデルエントリに legacy `context_window_tokens` が含まれる
- WHEN 設定を読み込む
- THEN システムはその値を `max_input_tokens` として扱い deprecation warning を出す、または設定を不正として拒否する
- AND legacy フィールドを silently ignore してはならない

#### Scenario: smart-proxy compaction context_window_tokens remains separate

- GIVEN `smart_proxy.context_compaction.context_window_tokens` が設定されている
- WHEN 設定を読み込む
- THEN システムはこの compaction 設定を従来通り受理する
- AND この値を per-model `max_input_tokens` として扱ってはならない
