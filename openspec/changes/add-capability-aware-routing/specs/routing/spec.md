## ADDED Requirements

### Requirement: 能力ベースのモデルフィルタリング

ルーターはリクエストが要求する能力を持つモデルのみを候補として選択しなければならない (SHALL)。

#### Scenario: Vision 対応モデルへのルーティング

- GIVEN リクエストのメッセージに `image_url` 型コンテンツブロックが含まれる
- AND `model_capabilities` に `vision` を持つプレフィックスが設定されている
- WHEN ルーティングを実行する
- THEN `vision` 能力を持つモデルのみが選択候補になる
- AND `vision` 能力を持たないモデルは候補から除外される

#### Scenario: ツールコール対応モデルへのルーティング

- GIVEN リクエスト body に `tools` または `functions` フィールドが存在する
- AND `model_capabilities` に `tools` を持つプレフィックスが設定されている
- WHEN ルーティングを実行する
- THEN `tools` 能力を持つモデルのみが選択候補になる

#### Scenario: JSON モード対応モデルへのルーティング

- GIVEN リクエスト body の `response_format.type` が `json_object` または `json_schema` である
- AND `model_capabilities` に `json_mode` を持つプレフィックスが設定されている
- WHEN ルーティングを実行する
- THEN `json_mode` 能力を持つモデルのみが選択候補になる

#### Scenario: required_capabilities が空の場合の後方互換

- GIVEN リクエストに `image_url`, `tools`, `response_format` のいずれも含まれない
- WHEN ルーティングを実行する
- THEN 能力フィルタリングは適用されず既存のロジックと同一の挙動になる

### Requirement: 能力不足時の Tier Escalation

tier 内に必要な能力を持つ候補がない場合、上位 tier に自動 escalate しなければならない (SHALL)。

#### Scenario: SIMPLE tier で capable 候補なし → MEDIUM へ escalate

- GIVEN ルーティング tier が SIMPLE に分類される
- AND SIMPLE tier の全候補モデルが `required_capabilities` を満たさない
- WHEN ルーティングを実行する
- THEN 次の tier (MEDIUM) の候補で再試行する
- AND escalation は `_fallback_tier_name` の既存ロジックに従う

### Requirement: 能力要件を満たす候補がない場合のエラー

全 tier 枯渇後も capable 候補がない場合、`CapabilityNotSatisfiedError` を raise しなければならない (SHALL)。

#### Scenario: 全 tier に capable モデルなし

- GIVEN プロファイル内の全ての tier の全候補が `required_capabilities` を満たさない
- WHEN ルーティングを実行する
- THEN `CapabilityNotSatisfiedError` を raise する
- AND proxy はこれを受けて HTTP 400 相当の JSON エラーを返す

### Requirement: ラウンドロビン選択は capable 候補のみ対象

ラウンドロビン選択は能力フィルタリング後の候補リストに対して行われなければならない (SHALL)。

#### Scenario: capable 候補のみでラウンドロビン

- GIVEN primary 候補 `[A, B, C]` のうち `B` のみが必要な能力を持つ
- WHEN 同一 `profile+tier` に連続でルーティングする
- THEN `B` のみが選択され続ける (ラウンドロビン対象は capable 候補のみ)

### Requirement: RoutingDecision への required_capabilities 記録

ルーティング決定に要求された能力セットを含めなければならない (SHALL)。

#### Scenario: required_capabilities のルーティング決定への付与

- GIVEN ルーティングが実行される
- WHEN RoutingDecision が返される
- THEN `required_capabilities` フィールドに検出された能力セットが含まれる
