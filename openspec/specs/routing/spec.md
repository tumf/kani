# Routing

## Purpose

プロンプトの複雑度を分類し、設定されたプロファイルとティア定義に基づいて最適なモデル・プロバイダの組み合わせを決定する。

## Requirements

### Requirement: ティア分類カスケード

プロンプト分類は 3 層カスケードで実行されなければならない (SHALL)。

#### Scenario: Embedding 分類器が高信頼度

- GIVEN embedding 分類器が利用可能である
- AND embedding の信頼度が 0.65 以上である
- WHEN プロンプトを分類する
- THEN embedding の分類結果を使用する
- AND LLM 分類器は呼び出されない
- AND signals.method は `embedding` である

#### Scenario: Embedding 分類器が低信頼度で LLM にエスカレーション

- GIVEN embedding 分類器が利用可能だが信頼度が 0.65 未満である
- AND LLM 分類器が有効である
- WHEN プロンプトを分類する
- THEN LLM 分類器にエスカレーションする
- AND LLM 分類器の結果は固定信頼度 0.8 で返される
- AND signals.method は `llm` である
- AND signals.embeddingConfidence に embedding の信頼度値が記録される

#### Scenario: LLM 分類器が無効で Embedding が低信頼度

- GIVEN embedding 分類器が利用可能だが信頼度が 0.65 未満である
- AND LLM 分類器が無効である
- WHEN プロンプトを分類する
- THEN embedding の低信頼度結果をそのまま使用する
- AND signals.method は `embedding-low-confidence` である

#### Scenario: すべての分類器が利用不可

- GIVEN embedding 分類器が利用不可である
- AND LLM 分類器も利用不可または失敗する
- WHEN プロンプトを分類する
- THEN デフォルトフォールバック結果を返す: tier=MEDIUM, confidence=0.35, score=0.0
- AND signals.method は `default` である

### Requirement: ティア定義

分類結果は 4 つのティアのいずれかでなければならない (SHALL)。

#### Scenario: 有効なティア値

- GIVEN プロンプトが分類される
- WHEN 分類結果が返される
- THEN tier は `SIMPLE`, `MEDIUM`, `COMPLEX`, `REASONING` のいずれかである

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

#### Scenario: 非 SIMPLE ティアでは Agentic 分類しない

- GIVEN ティア分類の結果が SIMPLE 以外である
- WHEN `classify_agentic=True` が指定されても
- THEN agentic 分類は実行されない

#### Scenario: classify_agentic=False

- GIVEN `classify_agentic=False` が指定される (デフォルト)
- WHEN 任意のティアのプロンプトが分類される
- THEN agentic 分類は実行されない

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

### Requirement: ティアフォールバック

指定されたティアがプロファイルに定義されていない場合、隣接ティアにフォールバックしなければならない (SHALL)。

#### Scenario: ティアが未定義の場合

- GIVEN ティア分類で `COMPLEX` が選択される
- AND プロファイルに `COMPLEX` ティアが定義されていない
- WHEN モデルを選択する
- THEN ティア順序 `[SIMPLE, MEDIUM, COMPLEX, REASONING]` に基づき、下方向優先で隣接ティアを探索する

### Requirement: プロバイダ解決優先順位

プロバイダは 3 段階の優先順位で解決されなければならない (SHALL)。

#### Scenario: プロバイダ解決の優先順位

- GIVEN モデルエントリにプロバイダ指定がある場合
- THEN そのプロバイダを使用する (最優先)
- GIVEN モデルエントリにプロバイダ指定がなく、ティア設定にプロバイダ指定がある場合
- THEN ティアレベルのプロバイダを使用する
- GIVEN いずれも指定がない場合
- THEN `default_provider` を使用する

### Requirement: メッセージ解析

ルーティングエンジンはメッセージ配列からプロンプトテキストを抽出しなければならない (SHALL)。

#### Scenario: テキストメッセージの抽出

- GIVEN メッセージ配列が与えられる
- WHEN プロンプトを抽出する
- THEN 最後の user メッセージのテキストを使用する
- AND system メッセージがあれば最後のものを連結する

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
- THEN 結果は `score` (float), `tier` (Tier), `confidence` (float), `signals` (dict), `agentic_score` (float) を含む
- AND `signals` には必ず `method` キーが含まれる
