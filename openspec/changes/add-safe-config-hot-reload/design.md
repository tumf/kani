# Design: safe config hot reload

## Overview

安全な hot reload は「新設定を作れるか」と「既存トラフィックを壊さず切り替えられるか」を分離して扱う。実装は単純な `configure()` 再実行ではなく、事前検証済みの新 state を組み立ててから一括で公開する方式を採る。

## Goals

- 再起動なしで config 変更を新規 request に反映する。
- 無効設定による部分適用を防ぐ。
- 進行中 request の整合性を壊さない。
- 管理操作を通常 API 利用者から分離する。
- smart-proxy worker を含む reload 対象を明示的に扱う。

## Non-Goals

- host / port の live rebinding。
- 複数ワーカープロセス間の同期。
- 自動 file watching。

## State Model

`src/kani/proxy.py` のグローバル state を単純な `_config`, `_router` のまま扱うより、reload 対象をひとまとまりの runtime state として扱う方が安全である。

想定 state:

- resolved config path
- active `KaniConfig`
- active `Router`
- active compaction worker metadata
- `config_loaded_at` / version counter

request handler は開始直後に active state をローカル変数へ退避して、その request の残り処理ではその参照だけを使う。これにより reload 中にグローバルが切り替わっても in-flight request は旧 state で完走できる。

## Reload Flow

1. 管理 API が Bearer admin token を検証する。
2. reload lock を取得し、二重 reload を防ぐ。
3. 現在の config path から `load_config(..., strict=True)` で新設定を読む。
4. `Router(new_config)` を構築する。
5. smart-proxy compaction 設定が有効なら、新 worker を事前に作成できることを確認する。
6. reload 非対応項目 (`host`, `port`) を現設定と比較する。
7. すべて成功した場合のみ active state を原子的に差し替える。
8. 差し替え後に旧 worker を graceful shutdown する。
9. 成功/失敗を運用ログへ記録し、呼び出し元へ JSON で返す。

途中で 1 つでも失敗したら active state は変更しない。

## Authentication

管理操作は通常 API key とは別境界にする。推奨は `KANI_ADMIN_TOKEN` で、`Authorization: Bearer <token>` を `POST /admin/reload-config` に必須化する。

理由:

- 通常クライアント用 API key に reload 権限を含めないため
- admin 操作の監査ログを区別しやすいため
- `has_keys() == False` でも admin endpoint を保護できるため

未設定時は endpoint を 403 あるいは 404 相当で扱い、誤って公開された管理面にならないようにする。

## Non-Reloadable Fields

`host` と `port` は uvicorn の listen socket に関わるため live reload しない。これらが変更された config を reload しようとした場合は、以下のどちらかを許容する。

- 推奨: API を失敗させ、再起動が必要なフィールド名を返す
- 代替: reload 可能部分のみ適用し、未適用フィールドを明示する

安全性を優先し、本 proposal では前者を推奨する。

## Compaction Worker Handling

compaction worker は現状 lifespan でのみ生成されるため、reload では専用の再初期化経路を持つ必要がある。

- disabled -> enabled: 新 worker を起動してから公開する
- enabled -> disabled: 新 state では worker なしにし、旧 worker を drain/shutdown する
- enabled -> enabled with changed settings: 新 worker を作って差し替える

進行中の compaction job は best-effort で完走または安全に shutdown させるが、client-facing request を壊さないことを優先する。

## Observability

reload 応答は少なくとも以下を含む:

- `ok`
- `reloaded`
- `config_path`
- `config_loaded_at`
- `changed` の要約
- `non_reloadable_changes` または `error`

ログには secrets を出さず、変更要約と結果のみ残す。
