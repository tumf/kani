## ADDED Requirements

### Requirement: 管理用 config hot reload エンドポイント

動作中の kani proxy は、再起動せずに設定を安全に再読込する管理用 API を提供しなければならない (SHALL)。

#### Scenario: 検証済み設定の reload 成功

- GIVEN 動作中の proxy が管理用認証情報つきで `POST /admin/reload-config` を受け取る
- AND 新しい config が `strict=True` での読込と Router 構築に成功する
- WHEN proxy が reload を実行する
- THEN 新しい config と Router を原子的に active state として公開する
- AND reload 成功を JSON で返す
- AND 成功ログを記録する

#### Scenario: reload 検証失敗時の現行設定維持

- GIVEN 動作中の proxy が `POST /admin/reload-config` を受け取る
- AND 新しい config の strict 読込、Router 構築、または reload 前提チェックのいずれかが失敗する
- WHEN proxy が reload を試みる
- THEN active な config と Router は変更されない
- AND エラー理由を JSON で返す
- AND 失敗ログを記録する

#### Scenario: in-flight request は開始時点の state で完走する

- GIVEN ある request が旧 config / Router を参照して処理を開始している
- AND 別の管理 request が hot reload を成功させる
- WHEN 先行 request が処理を継続する
- THEN 先行 request は開始時点の state を使って完走する
- AND reload 後に開始した新規 request のみが新 state を使う

### Requirement: reload 非対応変更の安全な拒否

proxy は live 適用できない設定変更を hot reload で安全に拒否しなければならない (SHALL)。

#### Scenario: bind 設定変更の拒否

- GIVEN 新しい config が `host` または `port` の変更を含む
- WHEN 管理者が `POST /admin/reload-config` を呼び出す
- THEN proxy は当該 reload を成功扱いで部分適用しない
- AND 再起動が必要なフィールド名を応答に含める
