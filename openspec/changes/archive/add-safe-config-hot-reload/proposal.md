# Add safe config hot reload

## Premise / Context

- ユーザー要望は「再起動せずに config を安全に reload したい」であり、単なる再読込ではなく安全性が最優先である。
- 現在の `kani serve` は起動時に `configure(config_path)` を一度だけ呼び、`_config` と `_router` をプロセスグローバルに保持し続ける (`src/kani/cli.py`, `src/kani/proxy.py`)。
- 動作中の再読込経路 (`/reload`, `SIGHUP`, watcher) は存在せず、compaction worker も lifespan 起動時にのみ初期化される (`src/kani/proxy.py`)。
- 認証は通常 API 用 Bearer key middleware があるが、管理操作専用の権限境界はまだない (`src/kani/api_keys.py`, `src/kani/proxy.py`)。
- OpenSpec には `config`, `proxy-api`, `auth`, `smart-proxy-context-compaction` の基盤仕様があり、今回の変更は再起動不要な運用改善としてそれらを横断する。

## Problem

Kani は設定変更を反映するためにプロセス再起動が必要であり、運用中のモデル切替、ルーティング調整、smart-proxy 設定変更の反映が重い。しかも単純に `load_config()` を呼び直すだけでは、無効な新設定の部分適用、進行中リクエストへの影響、compaction worker の不整合、管理操作の認可不足といった運用リスクがある。

## Proposed Solution

`POST /admin/reload-config` を追加し、管理用トークンで保護した明示的な hot reload フローを導入する。reload は「新設定の strict 検証」「新 Router 構築」「必要な smart-proxy リソースの事前準備」を完了した後に、ロック下で `_config` と `_router` を原子的に差し替える。失敗時は現行設定を維持し、進行中リクエストは開始時点の参照を使って完走させる。bind host / port のようなソケット再束縛が必要な項目は hot reload 対象外とし、再起動必須のまま残す。

## Acceptance Criteria

- 管理用認証が成功した場合に限り、`POST /admin/reload-config` で動作中プロセスが設定を再読込できる。
- reload は `load_config(..., strict=True)` 相当の検証と新 Router 構築に成功した場合のみ適用され、途中失敗時は旧設定を維持する。
- in-flight request は開始時点の config/router 参照で完走し、新規 request のみが新設定を使う。
- smart-proxy context compaction の有効/無効や worker concurrency 変更が reload 後の新規 request に反映される。
- bind host / port など再起動が必要な変更は明示的に非対応とし、reload API はそれを安全に扱う（拒否または未適用として報告する）。
- 監査可能なログとテストで、成功・認証失敗・検証失敗・部分適用防止・compaction worker 切替の回帰が確認できる。

## Out of Scope

- ファイル監視による自動 reload。
- プロセス間での分散同期 reload。
- host / port の live rebinding。
- upstream HTTP client の timeout / pool 設定を reload 対象に広げること。
