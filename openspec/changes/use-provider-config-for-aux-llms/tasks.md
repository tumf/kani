## Implementation Tasks

- [ ] Task 1: `LLMClassifierConfig` と `FeatureAnnotatorConfig` を `model` + 任意の `provider` のみを表す設定モデルへ更新し、`config.yaml` 上の `base_url` / `api_key` を受理しないようにする（`src/kani/config.py`）。(verification: config validation テスト追加/更新、`uv run pytest tests/ -q -k "config or annotator"`)
- [ ] Task 2: 補助 LLM 設定から provider 名を解決し、未指定時は `default_provider` を使って `base_url` / `api_key` を取得する共通ロジックを追加する（`src/kani/config.py`）。(verification: provider 指定・default_provider フォールバック・未知 provider の失敗ケースをテストで確認)
- [ ] Task 3: `FeatureAnnotator` が `feature_annotator` の provider 解決済み接続情報を使うよう更新し、`config.yaml` の新仕様に追従させる（`src/kani/training_data.py`）。(verification: `tests/test_agentic_training_data.py` を更新し、provider 指定 / default_provider の両ケースを確認)
- [ ] Task 4: サンプル設定と OpenSpec の config 差分を更新し、`llm_classifier` / `feature_annotator` が provider ベース設定へ統一されたことを明文化する（`config.yaml`, `openspec/changes/use-provider-config-for-aux-llms/specs/config/spec.md`）。(verification: `python3 "/Users/tumf/.agents/skills/cflx-proposal/scripts/cflx.py" validate use-provider-config-for-aux-llms --strict`)
- [ ] Task 5: 変更全体の品質ゲートを実行する。 (verification: `uv run ruff check src/`、`uv run ruff format --check src/ tests/`、`uv run pyright src/`、`uv run pytest tests/ -q`)

## Future Work

- `llm_classifier` の実利用箇所が増える場合、同じ provider 解決ヘルパーを共通利用して重複を避ける。
- 実行時 override（引数・環境変数）も provider ベースへ揃えるかは別提案で判断する。
