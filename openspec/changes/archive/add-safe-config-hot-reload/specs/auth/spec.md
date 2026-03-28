## ADDED Requirements

### Requirement: 管理 API の専用認証

設定 reload のような管理 API は、通常の client-facing API アクセスとは分離した管理用認証で保護されなければならない (SHALL)。

#### Scenario: 正しい管理トークンで reload を許可する

- GIVEN 管理用トークンがサーバに設定されている
- AND クライアントが `Authorization: Bearer <admin-token>` を付けて `POST /admin/reload-config` を送る
- WHEN サーバがリクエストを検証する
- THEN reload 処理を継続できる

#### Scenario: 管理トークンなしでは reload を拒否する

- GIVEN 管理用トークンが必要である
- WHEN クライアントがトークンなし、または不正なトークンで `POST /admin/reload-config` を送る
- THEN サーバは reload を実行しない
- AND 認証エラー応答を返す
