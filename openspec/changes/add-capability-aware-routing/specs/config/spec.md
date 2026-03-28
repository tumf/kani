## ADDED Requirements

### Requirement: モデル能力プレフィックス設定

設定はモデル名の前方一致プレフィックスで能力セットを宣言できなければならない (SHALL)。

#### Scenario: プレフィックスによる能力宣言

- GIVEN `model_capabilities` が `[{prefix, capabilities}]` 形式で設定される
- WHEN 設定を読み込む
- THEN 各エントリは `prefix` (文字列) と `capabilities` (文字列リスト) として検証される

#### Scenario: モデル名の前方一致

- GIVEN `model_capabilities` に `prefix: "claude-sonnet"` が設定されている
- WHEN モデル ID `claude-sonnet-4-6(high)` の能力を解決する
- THEN そのエントリの `capabilities` が適用される

#### Scenario: プレフィックス未一致モデル

- GIVEN `model_capabilities` のどの `prefix` にも一致しないモデル ID がある
- WHEN モデル能力を解決する
- THEN そのモデルの能力セットは空として扱われる

### Requirement: トップレベル設定への model_capabilities 追加

トップレベル設定に `model_capabilities` フィールドを含めることができなければならない (SHALL)。

#### Scenario: model_capabilities が未設定

- GIVEN `model_capabilities` が設定されていない
- WHEN 設定を読み込む
- THEN `model_capabilities` は空リストとして扱われる
- AND 既存設定の後方互換性が維持される

#### Scenario: model_capabilities が設定される

- GIVEN 有効な `model_capabilities` が設定ファイルに含まれる
- WHEN 設定を読み込む
- THEN `KaniConfig` からその設定を参照できる
