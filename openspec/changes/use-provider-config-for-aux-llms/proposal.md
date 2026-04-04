---
change_type: implementation
priority: medium
dependencies: []
references:
  - src/kani/config.py
  - src/kani/training_data.py
  - config.yaml
  - openspec/specs/config/spec.md
---
# Use provider-based config for auxiliary LLM settings

**Change Type**: implementation

## Premise / Context

- ユーザー要望は `config.yaml` の `llm_classifier` と `feature_annotator` で LLM 接続先を `provider` で指定できるようにし、未指定時は `default_provider` を使うこと。
- 追加制約として、この 2 セクションでは `base_url` / `api_key` を `config.yaml` 上で廃止することが明示された。
- 現行の canonical config spec は `llm_classifier.api_key` の優先順位解決を前提にしており、provider ベース解決を表していない (`openspec/specs/config/spec.md:130`)。
- 現行実装では `FeatureAnnotator` が `feature_annotator.base_url` / `api_key` を直接参照しており、provider 解決がない (`src/kani/training_data.py:64`)。
- 既存 routing spec には tier/model エントリ向けの provider 解決優先順位があり、未指定時に `default_provider` を使う方針はリポジトリ内で既に確立されている (`openspec/specs/routing/spec.md:191`)。

## Problem

`llm_classifier` と `feature_annotator` は、routing 本体とは別に `base_url` / `api_key` を個別記述する前提になっており、provider 設定との重複が発生する。これにより `config.yaml` の接続情報が二重管理になり、`default_provider` を切り替えても補助 LLM 設定が自動追従しない。

## Proposed Solution

`config.yaml` の `llm_classifier` と `feature_annotator` を `model` と任意の `provider` のみを受け付ける設定へ変更する。両セクションの接続情報 (`base_url`, `api_key`) は、指定された `provider`、または未指定時の `default_provider` から解決する。`config.yaml` 上で `base_url` / `api_key` を書いた場合は不正設定として扱う。既存の実行時 override（コード引数や環境変数）は本提案のスコープ外とし、`config.yaml` の記法と config 解決ロジックのみを更新する。

## Acceptance Criteria

- `config.yaml` の `llm_classifier` / `feature_annotator` は `model` と任意の `provider` を受け付ける。
- 上記 2 セクションで `provider` が未指定の場合、接続先は `default_provider` から解決される。
- 上記 2 セクションで `provider` が指定された場合、その provider の `base_url` / `api_key` が使われる。
- `config.yaml` の `llm_classifier` / `feature_annotator` で `base_url` または `api_key` を指定すると設定検証が失敗する。
- 指定した `provider` が `providers` に存在しない場合、または `default_provider` が解決不能な場合、設定検証が失敗する。
- `feature_annotator` を使う既存コードは、config 上の provider 解決済み接続情報を利用する。
- 関連する config / training_data テストと lint / format / typecheck が通る。

## Out of Scope

- `LLMFeatureAnnotator` コンストラクタ引数や `KANI_LLM_ANNOTATOR_*` 環境変数の廃止。
- `llm_classifier` 実行時 override の仕様変更。
- tier/model routing の provider 解決優先順位そのものの変更。
