## MODIFIED Requirements

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

## REMOVED Requirements

### Requirement: LLM 分類器の動作

蒸留特徴量方式への移行により、runtime LLM 分類器は廃止される。LLM はオフラインの教師データ生成のみに使用される。

### Requirement: ティア分類カスケード (旧 3 層カスケード)

embedding → LLM → default のカスケードは蒸留特徴量分類器に置き換えられる。
