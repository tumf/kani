## MODIFIED Requirements

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
