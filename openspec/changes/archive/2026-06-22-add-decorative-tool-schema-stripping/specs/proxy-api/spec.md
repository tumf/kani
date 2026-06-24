## MODIFIED Requirements

### Requirement: Chat Completions エンドポイント

`POST /v1/chat/completions` は OpenAI Chat Completions API 互換のリクエストを受け付け、ルーティングまたはパススルーでバックエンドプロバイダに転送しなければならない (SHALL)。Routed requests MAY receive opt-in payload adaptation that removes decorative top-level tool schema fields only when configuration explicitly enables it and the tools capability decision determines tools are declared but not required.

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

#### Scenario: decorative tool schema fields are preserved by default

**Given** a routed chat completion request contains top-level `tools`, `functions`, `tool_choice`, or `function_call` fields
**And** decorative tool schema handling is unset or set to `preserve`
**When** kani forwards the request upstream
**Then** kani MUST preserve those top-level fields in the upstream payload

#### Scenario: decorative tool schema fields are stripped only when not required

**Given** a routed chat completion request contains top-level `tools` or legacy `functions` declarations
**And** tools capability detection determines `declared=True` and `required=False`
**And** decorative tool schema handling is set to `strip`
**When** kani forwards the request upstream
**Then** kani MUST remove top-level `tools`, `functions`, `tool_choice`, and `function_call` fields from the upstream payload
**And** kani MUST preserve all message content and non-tool request fields

#### Scenario: required tool fields are never stripped

**Given** a routed chat completion request contains tool declarations
**And** tools capability detection determines `required=True` because tool use is forced or active
**And** decorative tool schema handling is set to `strip`
**When** kani forwards the request upstream
**Then** kani MUST preserve tool-related request fields needed to satisfy the client intent
**And** kani MUST continue requiring the `tools` capability during routing

#### Scenario: passthrough mode never strips decorative tool fields

**Given** a chat completion request contains top-level `tools`, `functions`, `tool_choice`, or `function_call` fields
**And** the `model` field does not start with `kani/`
**When** kani forwards the request in passthrough mode
**Then** kani MUST preserve the request payload's tool-related fields regardless of decorative tool schema handling configuration

#### Scenario: decorative stripping is auditable without schema leakage

**Given** decorative tool schema handling is set to `strip`
**And** a routed request contains decorative tool schema fields
**When** kani adapts the upstream payload
**Then** routing diagnostics or logs SHOULD indicate that decorative tool stripping was applied
**And** diagnostics MUST NOT include tool schema contents by default
