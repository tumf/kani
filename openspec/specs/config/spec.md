# Config

## Purpose

YAML 設定ファイルの読み込み、環境変数プレースホルダーの解決、Pydantic モデルによるバリデーションを行い、アプリケーション全体に設定を提供する。

## Requirements

### Requirement: 設定ファイル探索

設定ファイルは定義された優先順位で探索されなければならない (SHALL)。

#### Scenario: 設定ファイルの探索順序

- GIVEN 設定ファイルのパスが明示的に指定されていない
- WHEN 設定を読み込む
- THEN 以下の順序で設定ファイルを探索する:
  1. `$KANI_CONFIG` 環境変数で指定されたパス
  2. `./config.yaml` (カレントディレクトリ)
  3. `./config.yml`
  4. `$XDG_CONFIG_HOME/kani/config.yaml` (デフォルト: `~/.config/kani/config.yaml`)
  5. `/etc/kani/config.yaml`

#### Scenario: 明示的パス指定

- GIVEN `--config` 引数でパスが指定される
- WHEN 設定を読み込む
- THEN 指定されたパスのみを読み込む
- AND パスが存在しない場合は `ConfigNotFoundError` を発生させる

### Requirement: 環境変数解決

設定値内の `${VAR}` プレースホルダーは環境変数で置換されなければならない (SHALL)。

#### Scenario: 環境変数の展開

- GIVEN 設定値に `${OPENROUTER_API_KEY}` が含まれる
- AND 環境変数 `OPENROUTER_API_KEY` が設定されている
- WHEN 設定を読み込む
- THEN プレースホルダーは環境変数の値に置換される

#### Scenario: 未設定の環境変数

- GIVEN 設定値に `${UNDEFINED_VAR}` が含まれる
- AND 環境変数 `UNDEFINED_VAR` が設定されていない
- WHEN 設定を読み込む
- THEN プレースホルダーは空文字列に置換される

### Requirement: 再帰的環境変数解決

環境変数の解決はネストされた辞書やリストにも再帰的に適用されなければならない (SHALL)。

#### Scenario: ネストされた設定値の解決

- GIVEN providers の api_key に `${VAR}` が含まれる
- AND profiles 内のモデル定義にも `${VAR}` が含まれる
- WHEN 設定を読み込む
- THEN すべてのネストされた文字列値の `${VAR}` パターンが解決される

### Requirement: Strict モード

`strict=True` の場合、不完全な設定は例外を発生させなければならない (SHALL)。

#### Scenario: 設定ファイルが見つからない (strict)

- GIVEN `strict=True` で設定を読み込む
- AND 設定ファイルが見つからない
- WHEN `load_config()` を呼び出す
- THEN `ConfigNotFoundError` を発生させる
- AND 例外には検索パスの情報が含まれる

#### Scenario: profiles セクションが空 (strict)

- GIVEN `strict=True` で設定を読み込む
- AND 設定ファイルに `profiles` セクションがない、または空である
- WHEN `load_config()` を呼び出す
- THEN `ConfigIncompleteError` を発生させる

#### Scenario: Non-strict モードのデフォルト動作

- GIVEN `strict=False` (デフォルト) で設定を読み込む
- AND 設定ファイルが見つからない
- WHEN `load_config()` を呼び出す
- THEN デフォルト値の `KaniConfig` を返す
- AND 例外は発生しない

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
  - `model_rules` (list[ModelRuleEntry])
  - `model_capabilities` (legacy list[ModelRuleEntry])

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

### Requirement: モデルメタデータ規則

`model_rules` は prefix-based model metadata の primary configuration surface でなければならない (SHALL)。`model_capabilities` は legacy compatibility alias としてのみ扱われなければならない (SHALL)。

#### Scenario: model_rules primary metadata

- GIVEN `model_rules` に prefix, capabilities, reasoning_style, provider filter が設定されている
- WHEN 設定を読み込む
- THEN システムは `model_rules` をモデルメタデータ規則として保持する
- AND capability filtering と reasoning_style override は `model_rules` を参照する

#### Scenario: legacy model_capabilities alias

- GIVEN `model_rules` が未設定である
- AND `model_capabilities` に legacy capability entries が設定されている
- WHEN 設定を読み込む
- THEN システムは `model_capabilities` を `model_rules` に正規化する
- AND `model_capabilities` は後方互換の legacy alias として扱われる

#### Scenario: model_rules and legacy alias are mutually exclusive

- GIVEN `model_rules` と `model_capabilities` の両方が設定されている
- WHEN 設定を検証する
- THEN システムは曖昧なメタデータ設定として拒否する

#### Scenario: required capabilities fail closed

- GIVEN リクエストが `vision`, `tools`, または `json_mode` の capability を要求する
- AND 設定済み候補のどれも要求 capability set を宣言していない
- WHEN ルーティング候補を capability filtering する
- THEN システムは capability 不足候補を選択してはならない
- AND 利用可能な候補がない場合は capability-satisfied candidate がないことを示すエラーで fail closed する

### Requirement: オーバーライド

設定のオーバーライドは deep merge で適用されなければならない (SHALL)。

#### Scenario: Deep merge のオーバーライド

- GIVEN ベース設定とオーバーライドが与えられる
- WHEN `load_config(overrides=...)` を呼び出す
- THEN オーバーライドの値がベース設定に深くマージされる
- AND オーバーライドが優先される

### Requirement: LLM 分類器設定

LLM 分類器の設定はオプショナルで、API キーは複数のソースから解決される (SHALL)。

#### Scenario: LLM 分類器の API キー解決

- GIVEN `llm_classifier` が設定されている
- WHEN API キーが必要になる
- THEN 以下の優先順位で解決される:
  1. 設定ファイルの `api_key` フィールド
  2. `KANI_LLM_CLASSIFIER_API_KEY` 環境変数
  3. `OPENROUTER_API_KEY` 環境変数


#

### Requirement: LLM 分類器設定

`llm_classifier` はオプショナル設定であり、`config.yaml` 上では `model` と任意の `provider` のみを受け付けなければならない (SHALL)。接続先の `base_url` と `api_key` は、指定された provider、または未指定時の `default_provider` から解決されなければならない (SHALL)。

#### Scenario: provider を明示した LLM 分類器設定

- GIVEN `llm_classifier.model` が設定されている
- AND `llm_classifier.provider` が `providers` 内の既知 provider 名である
- WHEN 設定を読み込む
- THEN システムはその provider の `base_url` と `api_key` を LLM 分類器接続情報として解決する

#### Scenario: provider 未指定の LLM 分類器設定

- GIVEN `llm_classifier.model` が設定されている
- AND `llm_classifier.provider` が未指定である
- WHEN 設定を読み込む
- THEN システムは `default_provider` を用いて LLM 分類器接続情報を解決する

#### Scenario: 廃止された接続フィールドを含む

- GIVEN `llm_classifier` に `base_url` または `api_key` が含まれる
- WHEN 設定を検証する
- THEN システムはその設定を不正として拒否する

### Requirement: Feature annotator 設定

`feature_annotator` はオプショナル設定であり、`config.yaml` 上では `model` と任意の `provider` のみを受け付けなければならない (SHALL)。接続先の `base_url` と `api_key` は、指定された provider、または未指定時の `default_provider` から解決されなければならない (SHALL)。

#### Scenario: provider を明示した feature annotator 設定

- GIVEN `feature_annotator.model` が設定されている
- AND `feature_annotator.provider` が `providers` 内の既知 provider 名である
- WHEN 設定を読み込む
- THEN システムはその provider の `base_url` と `api_key` を feature annotator 接続情報として解決する

#### Scenario: provider 未指定の feature annotator 設定

- GIVEN `feature_annotator.model` が設定されている
- AND `feature_annotator.provider` が未指定である
- WHEN 設定を読み込む
- THEN システムは `default_provider` を用いて feature annotator 接続情報を解決する

#### Scenario: 未知の provider を指定する

- GIVEN `feature_annotator.provider` または `llm_classifier.provider` に `providers` に存在しない名前が設定されている
- WHEN 設定を検証する
- THEN システムはその設定を不正として拒否する

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
