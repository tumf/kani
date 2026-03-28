## Implementation Tasks

- [ ] 1. `src/kani/proxy.py` に reload 用の状態管理と直列化ロックを追加し、request handler が開始時点の config/router 参照を固定して使うよう整理する (verification: `tests/test_proxy.py` または新規 proxy reload tests で in-flight 相当の旧参照維持を確認)
- [ ] 2. `src/kani/proxy.py` に `POST /admin/reload-config` を追加し、`load_config(..., strict=True)`・新 `Router` 構築・原子的切替・失敗時ロールバックを実装する (verification: reload 成功/検証失敗/部分適用なしを確認する API テスト)
- [ ] 3. 管理用トークン認証を追加し、通常 API key と分離した admin 境界を `src/kani/proxy.py` と必要なら `src/kani/config.py` / docs に反映する (verification: token なし/誤 token/正 token の各ケースをテスト)
- [ ] 4. smart-proxy context compaction の worker 再初期化方針を実装し、enabled 切替や concurrency 変更が reload 後の新規 request に反映されるようにする (verification: `tests/test_compaction.py` もしくは専用 test で worker 再生成・disable 反映を確認)
- [ ] 5. reload 非対応項目 (`host`, `port` など) の扱いを実装し、拒否または未適用の応答・ログを定義する (verification: non-reloadable change を含む config で安全な応答を確認)
- [ ] 6. `README.md` と関連 OpenSpec baseline 更新に必要な実装側資料を整え、`uv run pytest tests/ -q`, `uv run pyright src/`, `uv run ruff check src/`, `uv run ruff format --check src/ tests/` の対象チェックを通す (verification: コマンド実行結果)

## Future Work

- ファイル watch や `SIGHUP` ベースの自動 reload を追加するかどうかの運用判断。
- 複数プロセス / 複数インスタンス環境での coordinated reload 戦略。
