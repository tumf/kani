# Routing

## Purpose

プロンプトの複雑度を分類し、設定されたプロファイルとティア定義に基づいて最適なモデル・プロバイダの組み合わせを決定する。

## Requirements

### Requirement: ティア分類カスケード

プロンプト分類は、利用可能な場合は runtime で読み込まれた learned distilled feature classifier により実行されなければならない (SHALL)。classifier が利用不可または推論に失敗した場合、runtime は heuristic semantic label fallback を使用せず、明示的な conservative default fallback に収束しなければならない (SHALL)。

#### Scenario: 蒸留特徴量分類器が利用可能

- GIVEN 蒸留特徴量分類器 (distilled feature model) が runtime で読み込み可能である
- AND embedding 設定が解決可能である
- WHEN プロンプトを分類する
- THEN tokenCount を deterministic に算出し、14 semantic dimensions を learned classifier で推定する
- AND 15 次元特徴量の重み付き合成スコアからティアを決定する
- AND signals.method は `distilled-features` である
- AND signals には learned classifier 由来の semantic labels と dimension ごとのスコアが含まれる
- AND signals.featureVersion は bundle の `feature_schema_version` から導出される

#### Scenario: 蒸留特徴量分類器が利用不可

- GIVEN 蒸留特徴量分類器が存在しない、読み込めない、または bundle schema が不正である
- WHEN プロンプトを分類する
- THEN デフォルトフォールバック結果を返す: tier=MEDIUM, confidence=0.35, score=0.0
- AND signals.method は `default` である
- AND heuristic semantic labels を runtime fallback として使用しない

#### Scenario: 蒸留特徴量分類器の推論が失敗

- GIVEN 蒸留特徴量分類器は読み込めた
- AND embedding 設定、embedding API、classifier prediction、または label decoding のいずれかが失敗する
- WHEN プロンプトを分類する
- THEN デフォルトフォールバック結果を返す: tier=MEDIUM, confidence=0.35, score=0.0
- AND signals.method は `default` である
- AND heuristic semantic labels を runtime fallback として使用しない

#### Scenario: embedding 呼び出しがタイムアウトする

- GIVEN 蒸留特徴量分類器は読み込めた
- AND runtime embedding 呼び出しが設定された timeout を超過する
- WHEN プロンプトを分類する
- THEN embedding 失敗として扱い、デフォルトフォールバック結果を返す: tier=MEDIUM, confidence=0.35, score=0.0
- AND signals.method は `default` である
- AND embedding timeout が routing 全体をブロックしない

### Requirement: ティア定義

分類結果は 4 つのティアのいずれかでなければならない (SHALL)。

#### Scenario: 有効なティア値

- GIVEN プロンプトが分類される
- WHEN 分類結果が返される
- THEN tier は `SIMPLE`, `MEDIUM`, `COMPLEX`, `REASONING` のいずれかである

#### Scenario: primary が単数で定義される

- GIVEN tier 設定の `primary` が文字列または `{model, provider}` オブジェクト単数である
- WHEN 設定を読み込む
- THEN システムはその候補を primary 候補列として受理する
- AND 従来互換のモデル・プロバイダ解決が維持される

#### Scenario: primary が複数で定義される

- GIVEN tier 設定の `primary` が文字列または `{model, provider}` の配列である
- WHEN 設定を読み込む
- THEN システムは配列順の primary 候補列として受理する
- AND 候補列は空であってはならない

### Requirement: LLM 分類器の動作

LLM 分類器は制約付きで動作しなければならない (SHALL)。

#### Scenario: LLM 分類器のタイムアウト

- GIVEN LLM 分類器が呼び出される
- WHEN バックエンドが 2 秒以内に応答しない
- THEN LLM 分類器は None を返す (フォールバックに進む)

#### Scenario: プロンプトの切り詰め

- GIVEN プロンプトが 500 文字を超える
- WHEN LLM 分類器に送信される
- THEN プロンプトは 500 文字に切り詰められる

#### Scenario: LLM 分類器の不正な応答

- GIVEN LLM 分類器が呼び出される
- WHEN 応答が有効なティア名でない
- THEN LLM 分類器は None を返す (フォールバックに進む)

### Requirement: Agentic 分類

SIMPLE ティアのプロンプトに対して、agentic/non-agentic の追加分類を行うことができる (MAY)。

#### Scenario: Agentic 分類の発動条件

- GIVEN `classify_agentic=True` が指定される
- AND ティア分類の結果が SIMPLE である
- WHEN agentic 分類が実行される
- THEN agentic embedding 分類器 (信頼度閾値 0.7) → agentic LLM 分類器のカスケードで分類する
- AND `agentic_score` が 0.0 (NON_AGENTIC) または 1.0 (AGENTIC) に設定される

### Requirement: プロファイル解決

ルーティングは指定されたプロファイルに基づいてモデルを選択しなければならない (SHALL)。

#### Scenario: 明示的プロファイル指定

- GIVEN `profile` パラメータが明示的に指定される
- WHEN ルーティングを実行する
- THEN 指定されたプロファイルの設定を使用する

#### Scenario: model フィールドからのプロファイル抽出

- GIVEN `model` が `kani/<profile>` 形式である
- WHEN プロファイルが明示的に指定されていない
- THEN `model` フィールドからプロファイル名を抽出する

#### Scenario: デフォルトプロファイルへのフォールバック

- GIVEN 指定されたプロファイルが設定に存在しない
- WHEN ルーティングを実行する
- THEN `default_profile` にフォールバックする
- AND 警告ログを出力する

### Requirement: Agentic プロファイルの SIMPLE 昇格

Agentic プロファイルでは、agentic スコアが高い SIMPLE プロンプトを MEDIUM に昇格しなければならない (SHALL)。

#### Scenario: SIMPLE から MEDIUM への昇格

- GIVEN ティア分類結果が SIMPLE である
- AND `agentic_score` が 0.6 を超える
- WHEN ルーティングを実行する
- THEN ティアを MEDIUM に昇格する

### Requirement: fallback null 正規化

`profiles.*.tiers.*.fallback` は `null` で記述されても tier fallback の空リストとして扱われなければならない (SHALL)。

#### Scenario: fallback が null として記述される

- GIVEN profiles 内の tier 設定で `fallback:` が YAML 上 `null` として解釈される
- WHEN 設定を読み込む
- THEN システムはその `fallback` を空リストとして正規化してから検証する
- AND 結果の tier 設定はフォールバックモデルを持たない
- AND 他の設定キーには同じ null 正規化を自動適用しない

### Requirement: Primary ラウンドロビン選択

ルーターは `profile+tier` 単位で primary 候補をラウンドロビン選択しなければならない (SHALL)。

#### Scenario: 同一 profile+tier で連続リクエスト

- GIVEN `primary` 候補列が `[A, B]` の `profile+tier` がある
- WHEN 同一 `profile+tier` に対して連続でルーティングを行う
- THEN 選択 primary は `A -> B -> A -> ...` の順で回転する

#### Scenario: tier 間で独立した回転状態

- GIVEN 複数 tier がそれぞれ複数 primary 候補を持つ
- WHEN 異なる tier へ交互にルーティングする
- THEN 各 tier の回転状態は相互に独立して進行する

### Requirement: ティアフォールバック

指定されたティアがプロファイルに定義されていない場合、隣接ティアにフォールバックしなければならない (SHALL)。

#### Scenario: ティアが未定義の場合

- GIVEN ティア分類で `COMPLEX` が選択される
- AND プロファイルに `COMPLEX` ティアが定義されていない
- WHEN モデルを選択する
- THEN ティア順序 `[SIMPLE, MEDIUM, COMPLEX, REASONING]` に基づき、下方向優先で隣接ティアを探索する

### Requirement: プロバイダ解決優先順位

プロバイダは 3 段階の優先順位で解決されなければならない (SHALL)。Routing documentation MUST clearly describe this provider resolution precedence and MUST clarify that configured model IDs are sent literally to the selected provider.

#### Scenario: プロバイダ解決の優先順位

- GIVEN モデルエントリにプロバイダ指定がある場合
- THEN そのプロバイダを使用する (最優先)
- GIVEN モデルエントリにプロバイダ指定がなく、ティア設定にプロバイダ指定がある場合
- THEN ティアレベルのプロバイダを使用する
- GIVEN いずれも指定がない場合
- THEN `default_provider` を使用する

#### Scenario: Model IDs are literal provider model IDs

**Given** an operator configures a tier `primary` or `fallback` model ID
**When** kani sends a routed request upstream
**Then** kani MUST send the configured model ID literally to the selected provider
**And** documentation MUST NOT imply an unsupported `provider/model` parsing syntax unless such parsing is actually implemented

### Requirement: メッセージ解析

ルーティングエンジンはメッセージ配列からプロンプトテキストを抽出しなければならない (SHALL)。

#### Scenario: テキストメッセージの抽出

- GIVEN メッセージ配列が与えられる
- WHEN プロンプトを抽出する
- THEN 最後の user メッセージのテキストを使用する
- AND system メッセージは分類用プロンプトテキストへ連結しない
- AND 最後の system メッセージは監査・デバッグ用メタデータとして保持してよい

#### Scenario: マルチモーダルコンテンツ

- GIVEN メッセージの content がコンテンツブロック配列である
- WHEN プロンプトを抽出する
- THEN テキスト部分のみを抽出する (画像等は無視)

### Requirement: ルーティングログ

すべてのルーティング決定を JSONL ファイルに記録しなければならない (SHALL)。

#### Scenario: ルーティング決定の記録

- GIVEN ルーティング決定が完了する
- WHEN 結果が返される前
- THEN JSONL ログファイルに決定内容を記録する
- AND ログにはタイムスタンプ、tier、score、confidence、model、provider、profile が含まれる
- AND ログ書き込みの失敗はルーティング処理をブロックしない

#### Scenario: プロンプトプレビューの切り詰め

- GIVEN プロンプトが 200 文字を超える
- WHEN ログに記録する
- THEN `prompt_preview` フィールドは 200 文字に切り詰められる

### Requirement: 分類結果の構造

分類結果は安定した構造で返されなければならない (SHALL)。

#### Scenario: ClassificationResult の形状

- GIVEN プロンプトが分類される
- WHEN 結果が返される
- THEN 結果は `score` (float), `tier` (Tier), `confidence` (float), `signals` (dict), `agentic_score` (float), `dimensions` (list) を含む
- AND `signals` には必ず `method` キーが含まれる
- AND learned classifier が成功した場合、`dimensions` には 15 次元の特徴量スコアが含まれる

### Requirement: Input-limit-aware candidate selection

Routing MUST avoid selecting model candidates whose configured input-token limit is smaller than the estimated request prompt tokens. The input-limit filter is authoritative for candidates that declare a limit: once a known-over-limit candidate is filtered out, routing MUST NOT reintroduce that candidate through a final default or upstream fallback path.

#### Scenario: Too-small primary is skipped

**Given**: A profile tier has primary candidates `small` and `large`
**And**: `small` has `max_input_tokens` lower than the estimated prompt tokens
**And**: `large` has `max_input_tokens` greater than or equal to the estimated prompt tokens
**When**: routing selects a model for the request
**Then**: kani MUST NOT select `small`
**And**: kani MAY select `large` if it satisfies the other routing requirements

#### Scenario: Unknown input limit remains eligible

**Given**: A model candidate does not declare `max_input_tokens`
**When**: routing evaluates input-limit eligibility
**Then**: kani MUST keep the candidate eligible for backward compatibility

#### Scenario: Capability filtering remains mandatory

**Given**: A candidate has enough `max_input_tokens`
**And**: the request requires a capability that candidate does not provide
**When**: routing evaluates candidates
**Then**: kani MUST NOT select that candidate

#### Scenario: Fallback or higher tier can satisfy long input

**Given**: all eligible primary candidates in the selected tier are too small
**And**: a fallback or higher-tier candidate has enough `max_input_tokens`
**When**: routing selects a model for the request
**Then**: kani MUST consider the fallback or higher-tier candidate using the same capability and input-limit checks

#### Scenario: No unsafe primary fallback when every known candidate is too small

**Given**: every configured candidate with a known `max_input_tokens` is lower than the estimated prompt tokens
**And**: no unknown-limit candidate is available
**When**: routing selects a model for the request
**Then**: kani MUST fail routing with a clear no-input-limit-eligible-candidate error
**And**: kani MUST NOT select any known-over-limit candidate as a final fallback

#### Scenario: Cooldown applies only after input-limit filtering

**Given**: multiple candidates fit the estimated prompt tokens
**And**: one fitted candidate is in fallback-backoff cooldown
**When**: routing selects a model for the request
**Then**: kani MUST skip the cooled candidate when another fitted candidate is available
**And**: if cooldown must be ignored because every fitted candidate is cooling down, kani MUST choose only from candidates that still fit the estimated prompt tokens

### Requirement: Offline annotation input limit parity

Offline feature annotation MUST use the same default maximum classification text length as runtime routing classification.

#### Scenario: Annotation prompt is bounded at runtime classification length

**Given** an offline annotation prompt longer than the runtime classification input maximum
**When** kani sends it to the LLM feature annotator
**Then** the prompt content sent to the annotator MUST be truncated to the runtime classification input maximum
**And** it MUST NOT exceed that maximum

#### Scenario: Annotation prompt is not truncated at the old shorter limit

**Given** an offline annotation prompt longer than 2000 characters but no longer than the runtime classification input maximum
**When** kani sends it to the LLM feature annotator
**Then** content beyond the 2000th character MUST remain available to the annotator

### Requirement: Offline feature annotator calibration

The offline feature annotator MUST provide semantic calibration guidance for every distilled routing semantic dimension when asking an LLM to label prompts.

#### Scenario: Annotator prompt includes dimension definitions

**Given** kani prepares an offline annotation request
**When** `LLMFeatureAnnotator` builds the annotator prompt
**Then** the prompt MUST include `low`, `medium`, and `high` calibration guidance for every semantic dimension
**And** the prompt MUST still require a JSON object containing exactly the semantic dimension keys

#### Scenario: Annotation parser remains strict

**Given** an annotator response omits a required dimension or returns a label outside `low`, `medium`, and `high`
**When** kani parses the annotation response
**Then** kani MUST reject that annotation result
**And** kani MUST NOT silently coerce unknown labels into valid labels

### Requirement: Lazy calibration prompt construction

The training-data annotation module MUST defer semantic-dimension calibration text construction until annotation prompt construction time, so that import-time failures do not block unrelated callers (implementation detail).

#### Scenario: Import does not eagerly validate calibration

- GIVEN the routing module defines `SEMANTIC_DIMENSIONS`
- AND the annotation module is imported
- WHEN the annotation module's training data classes are instantiated later
- THEN no semantic dimension calibration validation runs at import time

### Requirement: CLI output must not expose raw API keys

When the `kani` CLI serializes routing decisions or other data structures containing non-empty API key values, it MUST redact the raw key content and output a mask placeholder (e.g. `"***"`) instead. Empty API key values MUST remain unset/empty rather than being converted into a fake configured-secret marker.

#### Scenario: route command masks api_key in decision output

**Given** a valid config with a non-empty API key for the active provider
**When** `kani route "test prompt"` is executed
**Then** the JSON output must NOT contain the literal API key string
**And** the `"api_key"` field (both top-level and within fallback entries) must contain `"***"`

#### Scenario: route command preserves empty api_key values

**Given** a config where the provider API key is empty or unset
**When** `kani route "test prompt"` is executed
**Then** the JSON output must be valid and not raise any errors
**And** the corresponding `"api_key"` field must remain an empty string

### Requirement: Tools capability detection policy

Kani MUST determine whether a routed request requires the `tools` capability using the configured tools capability detection policy. The default policy MUST preserve declared-tool fail-closed behavior, while the opt-in active policy MAY treat decorative tool declarations as non-requirements when explicit or active tool use is absent.

#### Scenario: declared policy treats tool declarations as required

**Given** the tools capability detection policy is `declared`
**And** a routed chat completion request includes a `tools` or legacy `functions` field
**When** kani detects required capabilities
**Then** kani MUST include `tools` in the required capability set

#### Scenario: active policy ignores decorative tool declarations

**Given** the tools capability detection policy is `active`
**And** a routed chat completion request includes a `tools` or legacy `functions` field
**And** the request does not force tool use
**And** there is no assistant `tool_calls`, legacy assistant `function_call`, `role="tool"`, or legacy `role="function"` message after the latest user message
**When** kani detects required capabilities
**Then** kani MUST NOT include `tools` solely because tool declarations are present

#### Scenario: active policy preserves forced tool use

**Given** the tools capability detection policy is `active`
**And** a routed chat completion request includes a `tools` or legacy `functions` field
**And** the request uses `tool_choice`, legacy `function_call`, or another OpenAI-compatible request field to force a tool or function call
**When** kani detects required capabilities
**Then** kani MUST include `tools` in the required capability set

#### Scenario: active policy preserves active tool history

**Given** the tools capability detection policy is `active`
**And** a routed chat completion request includes a `tools` or legacy `functions` field
**And** after the latest user message, the message history contains assistant `tool_calls`, legacy assistant `function_call`, `role="tool"`, or legacy `role="function"`
**When** kani detects required capabilities
**Then** kani MUST include `tools` in the required capability set

#### Scenario: active policy ignores resolved historical tool activity

**Given** the tools capability detection policy is `active`
**And** a routed chat completion request includes a `tools` or legacy `functions` field
**And** tool activity exists only before the latest user message
**When** kani detects required capabilities
**Then** kani MUST NOT include `tools` because of that resolved historical activity

#### Scenario: tool-required requests still fail closed

**Given** a routed request requires the `tools` capability after applying the configured tools capability detection policy
**And** no configured model candidate declares the `tools` capability
**When** routing evaluates candidates
**Then** kani MUST fail routing with a clear capability-not-satisfied error
**And** kani MUST NOT select a candidate that lacks `tools`

#### Scenario: tools capability decision is auditable

**Given** a routed request includes a `tools` or legacy `functions` declaration
**When** kani detects required capabilities and routes the request
**Then** routing diagnostics or logs SHOULD indicate the configured tools detection policy and whether declarations, forced tool choice, or active tool history contributed to the final `tools` capability decision
**And** diagnostics MUST NOT log full tool schema contents by default
