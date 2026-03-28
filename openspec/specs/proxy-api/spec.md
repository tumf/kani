# Proxy API

## Purpose

OpenAI API 互換の HTTP プロキシ。クライアントからのリクエストを受け取り、ルーティングエンジンの判断に基づいて適切な LLM プロバイダにプロキシする。

## Requirements

### Requirement: Chat Completions エンドポイント

`POST /v1/chat/completions` は OpenAI Chat Completions API 互換のリクエストを受け付け、ルーティングまたはパススルーでバックエンドプロバイダに転送しなければならない (SHALL)。

#### Scenario: ルーティングモード (model が kani/ で始まる)

- GIVEN `model` フィールドが `kani/<profile>` 形式である
- WHEN クライアントが `POST /v1/chat/completions` にリクエストを送る
- THEN システムはプロファイル名を抽出し、ルーティングエンジンで最適なモデル・プロバイダを決定する
- AND リクエストの `model` フィールドを実際のモデル名に置き換える
- AND レスポンスヘッダに `X-Kani-Tier`, `X-Kani-Model`, `X-Kani-Provider`, `X-Kani-Score`, `X-Kani-Signals` を含める

#### Scenario: パススルーモード (model が kani/ で始まらない)

- GIVEN `model` フィールドが `kani/` で始まらない
- WHEN クライアントが `POST /v1/chat/completions` にリクエストを送る
- THEN システムは `default_provider` に直接転送する
- AND ルーティングエンジンを経由しない

#### Scenario: 不正な JSON ボディ

- GIVEN リクエストボディが有効な JSON ではない
- WHEN クライアントが `POST /v1/chat/completions` にリクエストを送る
- THEN ステータスコード 400 で OpenAI エラー形式のレスポンスを返す
- AND エラーメッセージは "Invalid JSON body" である

### Requirement: ストリーミングレスポンス

ストリーミングモードのリクエストは SSE 形式で中継されなければならない (SHALL)。

#### Scenario: stream=true のリクエスト

- GIVEN リクエストに `"stream": true` が含まれる
- WHEN バックエンドプロバイダがストリーミングレスポンスを返す
- THEN システムは `text/event-stream` としてクライアントに SSE データを中継する
- AND `stream_options.include_usage = true` をバックエンドリクエストに注入する
- AND 最終チャンクの usage 情報をログに記録する

#### Scenario: ストリーミングレスポンスのリトライ不可

- GIVEN リクエストが `stream=true` である
- WHEN プライマリモデルのバックエンドが 5xx エラーを返す
- THEN ストリーミングレスポンスはリトライされない

### Requirement: フォールバック

プライマリモデルが 5xx エラーを返した場合、フォールバックモデルに順次試行しなければならない (SHALL)。

#### Scenario: プライマリモデルの 5xx エラー (非ストリーミング)

- GIVEN ルーティング決定にフォールバックモデルが定義されている
- AND リクエストが非ストリーミングである
- WHEN プライマリモデルのバックエンドが 5xx ステータスを返す
- THEN 次のフォールバックモデルのバックエンドに同じリクエストを送る
- AND すべてのフォールバックが失敗するまで順次試行する

#### Scenario: 4xx エラーはリトライしない

- GIVEN バックエンドが 4xx ステータスを返す
- WHEN フォールバックモデルが存在する
- THEN リトライせずにクライアントにそのエラーレスポンスを返す

### Requirement: エラーレスポンス形式

すべてのエラーレスポンスは OpenAI API 互換の JSON 形式でなければならない (SHALL)。

#### Scenario: エラーレスポンスの構造

- GIVEN 任意のエラー状態が発生する
- WHEN システムがエラーレスポンスを返す
- THEN レスポンスボディは以下の形式である:
  ```json
  {
    "error": {
      "message": "<エラーメッセージ>",
      "type": "<エラータイプ>",
      "param": null,
      "code": null
    }
  }
  ```
- AND エラータイプは `invalid_request_error`, `upstream_error`, `timeout_error`, `router_error`, `authentication_error` のいずれかである

#### Scenario: バックエンドタイムアウト

- GIVEN バックエンドプロバイダが応答しない
- WHEN 接続またはリードタイムアウトが発生する
- THEN ステータスコード 504 でエラータイプ `timeout_error` を返す

#### Scenario: バックエンド接続エラー

- GIVEN バックエンドプロバイダに接続できない
- WHEN 接続エラーが発生する
- THEN ステータスコード 502 でエラータイプ `upstream_error` を返す

### Requirement: モデル一覧エンドポイント

`GET /v1/models` は利用可能なモデルの一覧を返さなければならない (SHALL)。

#### Scenario: モデル一覧の取得

- GIVEN サーバが起動している
- WHEN クライアントが `GET /v1/models` にリクエストを送る
- THEN プロファイルごとの仮想 `kani/*` モデルと、全プロファイルの実モデルを含む一覧を返す
- AND レスポンス形式は `{"object": "list", "data": [{"id": "...", "object": "model", ...}]}`

### Requirement: ルーティングデバッグエンドポイント

`POST /v1/route` はルーティング決定のみを返さなければならない (SHALL)。

#### Scenario: ルーティング決定の確認

- GIVEN 有効なメッセージ配列が指定される
- WHEN クライアントが `POST /v1/route` にリクエストを送る
- THEN バックエンドにプロキシせず、ルーティング決定のみを JSON で返す
- AND レスポンスには `model`, `provider`, `tier`, `score`, `confidence`, `fallbacks` が含まれる

### Requirement: ヘルスチェックエンドポイント

`GET /health` はサーバの状態を返さなければならない (SHALL)。

#### Scenario: ヘルスチェック

- GIVEN サーバが起動している
- WHEN クライアントが `GET /health` にリクエストを送る
- THEN ステータスコード 200 で `{"status": "ok", "version": "0.1.0"}` を返す
- AND 認証は不要である

### Requirement: URL 構築

バックエンドプロバイダの URL は正規化されなければならない (SHALL)。

#### Scenario: base_url が /v1 で終わる場合

- GIVEN プロバイダの `base_url` が `/v1` で終わる
- WHEN プロキシリクエストを構築する
- THEN URL は `{base_url}/chat/completions` となる

#### Scenario: base_url が /v1 で終わらない場合

- GIVEN プロバイダの `base_url` が `/v1` で終わらない
- WHEN プロキシリクエストを構築する
- THEN URL は `{base_url}/v1/chat/completions` となる

### Requirement: 使用量ログ

リクエスト完了時にトークン使用量を記録しなければならない (SHALL)。

#### Scenario: 非ストリーミングリクエストの使用量記録

- GIVEN 非ストリーミングリクエストが正常に完了する
- WHEN レスポンスに usage 情報が含まれる
- THEN stderr に `USAGE request_id=... model=... provider=... prompt=... completion=... total=... profile=... elapsed_ms=...` を出力する
- AND JSONL 実行ログに記録する

### Requirement: レスポンスヘッダ (ルーティングモード)

ルーティングモードでは、ルーティング決定の情報をレスポンスヘッダに含めなければならない (SHALL)。

#### Scenario: ルーティングヘッダの付与

- GIVEN `model` が `kani/` で始まるルーティングモードのリクエスト
- WHEN レスポンスを返す
- THEN 以下のヘッダを含める:
  - `X-Kani-Tier`: 分類ティア名
  - `X-Kani-Model`: 選択されたモデル名
  - `X-Kani-Provider`: 選択されたプロバイダ名
  - `X-Kani-Score`: スコア値 (小数点4桁)
  - `X-Kani-Signals`: シグナル JSON 文字列


#