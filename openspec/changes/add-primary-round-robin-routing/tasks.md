## Implementation Tasks

- [ ] Task 1: `TierModelConfig` の `primary` 型を後方互換で拡張し、単数/複数を正規化して取得できるヘルパーを追加する（`src/kani/config.py`）。(verification: `uv run pyright src/` と型整合、既存単数設定の読み込み回帰テスト)
- [ ] Task 2: `Router` に `profile+tier` 単位のラウンドロビン選択ロジックを追加し、`route()` と `resolve_model()` で primary 解決に利用する（`src/kani/router.py`）。(verification: round-robin 挙動テスト追加/更新、`uv run pytest tests/ -q -k "router or compaction"`)
- [ ] Task 3: primary 失敗時に fallback 試行列から同一 `model+provider` を除外し、fallback 内重複も一意化するロジックを追加する（`src/kani/proxy.py`）。(verification: retry シーケンステスト追加/更新、`uv run pytest tests/ -q -k "proxy or api_keys_proxy"`)
- [ ] Task 4: モデル一覧収集で複数 primary を列挙できるようにし、重複モデルIDを従来どおり除去する（`src/kani/proxy.py` `_collect_models`）。(verification: models list 回帰テスト、`uv run pytest tests/ -q -k models`)
- [ ] Task 5: 設定例と routing spec を更新し、複数 primary・RR・重複リトライ除外を明文化する（`config.yaml`, `README.md`, `openspec/specs/routing/spec.md`）。(verification: 文書レビュー + `python3 "/Users/tumf/.agents/skills/openclaw-imports/cflx-proposal/scripts/cflx.py" validate add-primary-round-robin-routing --strict`)
- [ ] Task 6: 変更全体の品質ゲートを実行する（lint/format/typecheck/tests）。(verification: `uv run ruff check src/`、`uv run ruff format --check src/ tests/`、`uv run pyright src/`、`uv run pytest tests/ -q`)

## Future Work

- マルチプロセス配備での厳密なグローバル RR が必要な場合、共有ストア（Redis/DB）でのカウンタ同期を別提案で検討する。
- provider 健全性に応じた動的な候補スキップ（サーキットブレーカー）を別提案で検討する。
