## MODIFIED Requirements

### Requirement: 設定スキーマ

設定は以下の構造に従わなければならない (SHALL)。

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
- AND `fallback` リスト内の各エントリは文字列またはモデル名+プロバイダ名のオブジェクトである
