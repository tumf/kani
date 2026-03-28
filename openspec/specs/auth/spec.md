# Auth

## Purpose

API キーの生成・管理・検証を行い、プロキシへのアクセスを制御する認証システム。

## Requirements

### Requirement: API キーの生成

API キーはセキュアに生成されなければならない (SHALL)。

#### Scenario: 新しい API キーの生成

- GIVEN 名前が指定される
- WHEN `generate_key(name)` を呼び出す
- THEN `kani-{token}` 形式の生キーが返される (token は `secrets.token_urlsafe(32)`)
- AND キーの SHA-256 ハッシュとプレフィックス (先頭 8 文字) と名前がストレージに保存される
- AND 生キーはこの時点でのみ利用可能であり、以降は取得できない

### Requirement: API キーの検証

API キーはハッシュベースで検証されなければならない (SHALL)。

#### Scenario: 有効なキーの検証

- GIVEN 生成済みの API キーがある
- WHEN `validate_key(raw_key)` を呼び出す
- THEN 生キーの SHA-256 ハッシュが保存済みハッシュと一致する場合 `True` を返す

#### Scenario: 無効なキーの検証

- GIVEN 存在しないまたは不正な API キー
- WHEN `validate_key(raw_key)` を呼び出す
- THEN `False` を返す

### Requirement: API キーの一覧

保存されたキーの一覧を取得できなければならない (SHALL)。

#### Scenario: キー一覧の取得

- GIVEN API キーが 1 つ以上生成されている
- WHEN `list_keys()` を呼び出す
- THEN 各キーの名前とプレフィックス (先頭 8 文字) を含むリストを返す
- AND 生キーやハッシュは含まれない

### Requirement: API キーの削除

API キーは名前またはプレフィックスで削除できなければならない (SHALL)。

#### Scenario: 名前での削除

- GIVEN 名前 "mykey" の API キーが存在する
- WHEN `remove_key("mykey")` を呼び出す
- THEN キーが削除され `True` を返す

#### Scenario: プレフィックスでの削除

- GIVEN プレフィックスが "kani-abc" の API キーが存在する
- WHEN `remove_key("kani-abc")` を呼び出す
- THEN キーが削除され `True` を返す

#### Scenario: 存在しないキーの削除

- GIVEN 識別子に一致するキーが存在しない
- WHEN `remove_key("nonexistent")` を呼び出す
- THEN `False` を返す

### Requirement: API キーストレージ

API キーは安全にファイルに保存されなければならない (SHALL)。

#### Scenario: ストレージの場所と形式

- GIVEN API キーが操作される
- WHEN ストレージにアクセスする
- THEN `$XDG_DATA_HOME/kani/api_keys.json` (デフォルト: `~/.local/share/kani/api_keys.json`) を使用する
- AND ファイル形式は JSON 配列で、各エントリは `name`, `key_hash`, `prefix` を含む

#### Scenario: ストレージファイルが存在しない場合

- GIVEN `api_keys.json` が存在しない
- WHEN `list_keys()` または `validate_key()` を呼び出す
- THEN 空リストまたは `False` を返す (クラッシュしない)

### Requirement: HTTP 認証ミドルウェア

プロキシは API キーの設定状態に基づいて認証を制御しなければならない (SHALL)。

#### Scenario: キー未設定時の後方互換

- GIVEN API キーが 1 つも設定されていない (`has_keys() == False`)
- WHEN クライアントが任意のエンドポイントにリクエストを送る
- THEN すべてのリクエストを認証なしで通す

#### Scenario: キー設定時の認証要求

- GIVEN API キーが 1 つ以上設定されている
- WHEN クライアントが保護対象エンドポイントにリクエストを送る
- THEN `Authorization: Bearer <key>` ヘッダが必要である
- AND ヘッダがない、またはキーが無効な場合はステータスコード 401 を返す
- AND エラータイプは `authentication_error` である

#### Scenario: 認証免除パス

- GIVEN API キーが設定されている
- WHEN クライアントが以下のパスにリクエストを送る:
  - `/health`
  - `/docs`
  - `/openapi.json`
- THEN 認証なしでリクエストを通す


#