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

#### Scenario: primary と fallback が重複する

- GIVEN 選択された primary 候補 `A` が失敗し、fallback 列に同一 `model+provider` の `A` が含まれる
- WHEN フォールバック試行列を構築する
- THEN システムはその `A` を除外する
- AND 同一リクエスト内で失敗済み primary を再試行しない

#### Scenario: fallback 内の重複候補

- GIVEN fallback 列に同一 `model+provider` 候補が複数回含まれる
- WHEN フォールバック試行列を構築する
- THEN システムは設定順を維持しつつ重複候補を一意化する
- AND 各候補は最大 1 回だけ試行される

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

#

### Requirement: Provider-specific reasoning control injection

Routed chat completion requests SHOULD receive provider-specific reasoning control payload fields when kani can infer an appropriate default and the client has not already provided reasoning or thinking controls.

#### Scenario: OpenAI-style reasoning injection

**Given**: a routed request selects a provider with `reasoning_style: openai`
**And**: the client request contains no explicit reasoning or thinking control field
**When**: kani proxies the request upstream
**Then**: kani SHOULD include `reasoning: {"effort": "<effort>"}` in the upstream payload
**And**: kani MUST preserve the selected actual model in `model`

#### Scenario: Anthropic-style effort injection

**Given**: a routed request selects a provider with `reasoning_style: anthropic`
**And**: the client request contains no explicit reasoning or thinking control field
**When**: kani proxies the request upstream
**Then**: kani SHOULD include `output_config.effort` in the upstream payload
**And**: kani MUST preserve unrelated `output_config` fields if present

#### Scenario: DashScope-style thinking injection

**Given**: a routed request selects a provider with `reasoning_style: dashscope`
**And**: the client request contains no explicit reasoning or thinking control field
**When**: kani proxies the request upstream
**Then**: kani SHOULD include `enable_thinking` in the upstream payload

#### Scenario: Gemini-style thinking budget injection

**Given**: a routed request selects a provider with `reasoning_style: gemini`
**And**: the client request contains no explicit reasoning or thinking control field
**When**: kani proxies the request upstream
**Then**: kani SHOULD include `generationConfig.thinkingConfig.thinkingBudget` in the upstream payload
**And**: kani MUST preserve unrelated `generationConfig` and `thinkingConfig` fields if present

#### Scenario: Reasoning injection disabled

**Given**: a routed request selects a provider with `reasoning_style: none`
**When**: kani proxies the request upstream
**Then**: kani MUST NOT add reasoning or thinking control fields for this feature

#### Scenario: Client-provided controls are preserved

**Given**: a routed request includes any of `reasoning`, `reasoning_effort`, `thinking`, `output_config.effort`, `enable_thinking`, or `generationConfig.thinkingConfig.thinkingBudget`
**When**: kani proxies the request upstream
**Then**: kani MUST NOT overwrite that client-provided reasoning or thinking control
**And**: kani MUST NOT add a second provider-specific reasoning control that conflicts with the client-provided control

#### Scenario: Pass-through requests are not modified

**Given**: `model` does not start with `kani/`
**When**: kani proxies the request to `default_provider`
**Then**: kani MUST NOT add reasoning or thinking control fields for this feature

#### Scenario: Fallback provider uses its own reasoning style

**Given**: a routed request fails on the primary candidate and retries a fallback candidate
**And**: the fallback candidate resolves to a provider with a different `reasoning_style` than the primary provider
**When**: kani builds the fallback upstream payload
**Then**: kani MUST apply the fallback provider's `reasoning_style`
**And**: kani MUST NOT reuse stale primary-provider reasoning controls that conflict with the fallback provider style

### Requirement: Reasoning message-field compatibility for routed requests

For routed chat completion requests, kani MUST adapt explicitly covered message-level reasoning metadata fields, starting with `messages[].reasoning_content`, to the selected upstream provider/model before proxying the request.

#### Scenario: Unsupported reasoning_content is stripped for primary upstream

**Given** a routed chat completion request contains `messages[].reasoning_content`
**And** the selected primary model/provider does not explicitly declare support via the repo-local compatibility flag defined by this change
**When** kani builds the upstream request payload
**Then** kani MUST remove `reasoning_content` from messages before sending the request upstream
**And** kani MUST preserve ordinary message `role` and `content` fields

#### Scenario: Fallback upstream uses fallback compatibility rules

**Given** a routed chat completion request retries a fallback model/provider after primary failure
**And** the fallback model/provider does not explicitly declare support for `messages[].reasoning_content` via the repo-local compatibility flag defined by this change
**When** kani builds the fallback upstream request payload
**Then** kani MUST remove `reasoning_content` according to the fallback model/provider compatibility rules
**And** kani MUST NOT reuse stale primary-provider compatibility assumptions

#### Scenario: Explicitly supported reasoning_content is preserved

**Given** a selected model/provider explicitly declares support for `messages[].reasoning_content` via the repo-local compatibility flag defined by this change
**When** kani builds the upstream request payload
**Then** kani MUST preserve `reasoning_content` in messages

#### Scenario: Pass-through requests are unchanged

**Given** a chat completion request uses a model that does not start with `kani/`
**When** kani proxies the request to the default provider
**Then** kani MUST NOT apply routed-request reasoning message-field sanitization for this feature

#### Scenario: reasoning_content does not force tier escalation

**Given** a conversation history contains `messages[].reasoning_content`
**And** the current user message is otherwise simple
**When** kani classifies the request for routing
**Then** kani MUST classify based on prompt/content difficulty
**And** kani MUST NOT force a higher tier solely because the metadata field exists
