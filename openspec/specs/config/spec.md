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

#### Scenario: プロファイル設定

- GIVEN profiles セクション内のエントリ
- WHEN バリデーションを行う
- THEN 各プロファイルは `tiers` ディクショナリを含む
- AND 各ティアは `primary` モデルと任意の `fallback` リストを含む
- AND `fallback` リスト内の各エントリは文字列またはモデル名+プロバイダ名のオブジェクトである

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
