## MODIFIED Requirements

### Requirement: 設定スキーマ

設定は以下の構造に従わなければならない (SHALL)。Profile tier model entries MAY include optional context-window metadata for routing-time candidate filtering.

#### Scenario: プロファイル設定

- GIVEN profiles セクション内のエントリ
- WHEN バリデーションを行う
- THEN 各プロファイルは `tiers` ディクショナリを含む
- AND 各ティアは `primary` モデルと任意の `fallback` リストを含む
- AND `primary` と `fallback` の各エントリは文字列またはモデル名+任意のプロバイダ名+任意の `context_window_tokens` を含むオブジェクトである

#### Scenario: context_window_tokens を含むモデルエントリ

- GIVEN tier 設定の `primary` または `fallback` に `{model, provider, context_window_tokens}` オブジェクトがある
- WHEN 設定を読み込む
- THEN システムは `context_window_tokens` をそのモデル候補の最大コンテキスト長として保持する
- AND `provider` が未指定の場合は既存の provider 解決優先順位を維持する

#### Scenario: 文字列モデルエントリの後方互換

- GIVEN tier 設定の `primary` または `fallback` が文字列モデル ID である
- WHEN 設定を読み込む
- THEN システムは従来通りその候補を受理する
- AND context window は未指定として扱う
