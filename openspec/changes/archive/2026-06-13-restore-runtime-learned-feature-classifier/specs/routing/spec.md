## MODIFIED Requirements

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
