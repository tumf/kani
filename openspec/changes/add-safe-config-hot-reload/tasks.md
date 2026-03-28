## Implementation Tasks

- [x] 1. `src/kani/proxy.py` に reload 用の状態管理と直列化ロックを追加し、request handler が開始時点の config/router 参照を固定して使うよう整理する (verification: `tests/test_proxy_reload.py::TestInFlightSnapshotBehavior::test_routed_request_keeps_start_of_request_state`)
- [x] 2. `src/kani/proxy.py` に `POST /admin/reload-config` を追加し、`load_config(..., strict=True)`・新 `Router` 構築・原子的切替・失敗時ロールバックを実装する (verification: `tests/test_proxy_reload.py::TestAdminReloadBehavior`)
- [x] 3. 管理用トークン認証を追加し、通常 API key と分離した admin 境界を `src/kani/proxy.py` と必要なら `src/kani/config.py` / docs に反映する (verification: `tests/test_proxy_reload.py::TestAdminReloadAuth`)
- [x] 4. smart-proxy context compaction の worker 再初期化方針を実装し、enabled 切替や concurrency 変更が reload 後の新規 request に反映されるようにする (verification: `tests/test_proxy_reload.py::TestCompactionWorkerReload`)
- [x] 5. reload 非対応項目 (`host`, `port` など) の扱いを実装し、拒否または未適用の応答・ログを定義する (verification: `tests/test_proxy_reload.py::TestAdminReloadBehavior::test_reload_rejects_non_reloadable_fields`)
- [x] 6. `README.md` と関連 OpenSpec baseline 更新に必要な実装側資料を整え、`uv run pytest tests/ -q`, `uv run pyright src/`, `uv run ruff check src/`, `uv run ruff format --check src/ tests/` の対象チェックを通す (verification: コマンド実行結果)

## Future Work

- ファイル watch や `SIGHUP` ベースの自動 reload を追加するかどうかの運用判断。
- 複数プロセス / 複数インスタンス環境での coordinated reload 戦略。
