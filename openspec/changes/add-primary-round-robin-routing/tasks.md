## Implementation Tasks

- [x] Task 1: `profiles.*.tiers.*.fallback` に限って `null` を `[]` に正規化し、`TierModelConfig` の `primary` も後方互換で単数/複数を受け付けるよう設定モデルと読み込みを拡張する（`src/kani/config.py`）。(verification: `uv run pyright src/` と config回帰テストで `fallback: null` 受理 + 既存単数設定維持)
- [x] Task 2: `Router` に `profile+tier` 単位のラウンドロビン選択ロジックを追加し、`route()` と `resolve_model()` で primary 解決に利用する（`src/kani/router.py`）。(verification: round-robin 挙動テスト追加/更新、`uv run pytest tests/ -q -k "router or compaction"`)
- [x] Task 3: primary 失敗時に fallback 試行列から同一 `model+provider` を除外し、fallback 内重複も一意化するロジックを追加する（`src/kani/proxy.py`）。(verification: retry シーケンステスト追加/更新、`uv run pytest tests/ -q -k "proxy or api_keys_proxy"`)
- [x] Task 4: モデル一覧収集で複数 primary を列挙できるようにし、重複モデルIDを従来どおり除去する（`src/kani/proxy.py` `_collect_models`）。(verification: models list 回帰テスト、`uv run pytest tests/ -q -k models`)
- [x] Task 5: 設定例と routing/config spec を更新し、複数 primary・RR・重複リトライ除外・`fallback: null` 正規化を明文化する（`config.yaml`, `README.md`, `openspec/specs/routing/spec.md` ほか必要な spec）。(verification: 文書レビュー + `python3 "/Users/tumf/.agents/skills/openclaw-imports/cflx-proposal/scripts/cflx.py" validate add-primary-round-robin-routing --strict`)
- [x] Task 6: `fix-config-null-fallback` 提案を削除し、本提案へ統合済みであることを差分上で明確にする。 (verification: `openspec/changes/fix-config-null-fallback/` が消えており、本提案内に null fallback 要件/タスクが存在することを確認)
- [x] Task 7: 変更全体の品質ゲートを実行する（lint/format/typecheck/tests）。(verification: `uv run ruff check src/`、`uv run ruff format --check src/ tests/`、`uv run pyright src/`、`uv run pytest tests/ -q`)

## Future Work

- マルチプロセス配備での厳密なグローバル RR が必要な場合、共有ストア（Redis/DB）でのカウンタ同期を別提案で検討する。
- provider 健全性に応じた動的な候補スキップ（サーキットブレーカー）を別提案で検討する。
