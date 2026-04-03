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


#


### Requirement: ティア分類カスケード

プロンプト分類は 15 次元特徴量ベースの蒸留分類器で実行されなければならない (SHALL)。

#### Scenario: 蒸留特徴量分類器が利用可能

- GIVEN 蒸留特徴量分類器 (distilled feature model) が利用可能である
- WHEN プロンプトを分類する
- THEN tokenCount を deterministic に算出し、14 semantic dimensions を learned classifier で推定する
- AND 15 次元特徴量の重み付き合成スコアからティアを決定する
- AND signals.method は `distilled-features` である
- AND signals には dimension ごとのスコアが含まれる

#### Scenario: 蒸留特徴量分類器が利用不可

- GIVEN 蒸留特徴量分類器が利用不可である
- WHEN プロンプトを分類する
- THEN デフォルトフォールバック結果を返す: tier=MEDIUM, confidence=0.35, score=0.0
- AND signals.method は `default` である

### Requirement: Agentic 分類

Agentic 判定は 15 次元特徴量の `agenticTask` dimension から導出されなければならない (SHALL)。

#### Scenario: agenticTask dimension からの agentic_score 導出

- GIVEN プロンプトが蒸留特徴量分類器で分類される
- WHEN 分類結果が返される
- THEN `agentic_score` は `agenticTask` dimension の数値化された値 (low=0.0, medium=0.5, high=1.0) である
- AND 独立した agentic classifier は呼び出されない

#### Scenario: classify_agentic フラグの廃止

- GIVEN 蒸留特徴量分類器が使用される
- WHEN 任意のプロンプトが分類される
- THEN `agentic_score` は常に算出される (ティアに依存しない)
- AND `classify_agentic` フラグによる条件分岐は行われない

### Requirement: 分類結果の構造

分類結果は安定した構造で返されなければならない (SHALL)。

#### Scenario: ClassificationResult の形状

- GIVEN プロンプトが分類される
- WHEN 結果が返される
- THEN 結果は `score` (float), `tier` (Tier), `confidence` (float), `signals` (dict), `agentic_score` (float), `dimensions` (list) を含む
- AND `signals` には必ず `method` キーが含まれる
- AND `dimensions` には 15 次元の特徴量スコアが含まれる


### Requirement: LLM 分類器の動作

蒸留特徴量方式への移行により、runtime LLM 分類器は廃止される。LLM はオフラインの教師データ生成のみに使用される。

### Requirement: ティア分類カスケード (旧 3 層カスケード)

embedding → LLM → default のカスケードは蒸留特徴量分類器に置き換えられる。


### Requirement: メッセージ解析

ルーティングエンジンはメッセージ配列から、会話文脈を反映した分類入力テキストを構築しなければならない (SHALL)。

#### Scenario: 直近会話文脈を用いた分類入力

- GIVEN メッセージ配列が与えられる
- WHEN ルーティング分類入力を構築する
- THEN システムは最後の user message 単体ではなく、関連する system prompt と直近の会話文脈を反映した分類入力テキストを生成する
- AND その分類入力テキストを scorer に渡す

#### Scenario: 短い継続メッセージの文脈継承

- GIVEN 最後の user message が「はい」「続けて」など単独では情報量が低い継続メッセージである
- AND 直前までの会話にアクティブなタスク文脈が存在する
- WHEN ルーティング分類を実行する
- THEN システムは直前のタスク文脈を含めた分類入力を構築する
- AND 継続メッセージ単体を low-context prompt として扱わない

#### Scenario: 分類入力の上限

- GIVEN 会話履歴が長い
- WHEN 分類入力テキストを構築する
- THEN システムは deterministic な上限ルールに従って関連文脈のみを含める
- AND 無制限に全履歴を分類入力へ連結しない

### Requirement: ルーティングログ

すべてのルーティング決定を JSONL ファイルに記録しなければならない (SHALL)。

#### Scenario: 分類入力文脈の再現性

- GIVEN ルーティング決定が完了する
- WHEN 結果が記録される
- THEN ログには分類に使った会話文脈を再現または監査できるだけの情報が含まれる
- AND 後続の分析や学習データ生成で runtime と同じ分類入力意味論を再利用できる