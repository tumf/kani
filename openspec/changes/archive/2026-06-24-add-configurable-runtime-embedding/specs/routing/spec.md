## MODIFIED Requirements

### Requirement: ティア分類カスケード

プロンプト分類は、利用可能な場合は runtime で読み込まれた learned distilled feature classifier により実行されなければならない (SHALL)。classifier が利用不可または推論に失敗した場合、runtime は heuristic semantic label fallback を使用せず、明示的な conservative default fallback に収束しなければならない (SHALL)。Runtime embedding execution MUST honor the configured embedding backend, model identity, and timeout.

#### Scenario: 蒸留特徴量分類器が利用可能

- GIVEN 蒸留特徴量分類器 (distilled feature model) が runtime で読み込み可能である
- AND embedding 設定が解決可能である
- WHEN プロンプトを分類する
- THEN tokenCount を deterministic に算出し、14 semantic dimensions を learned classifier で推定する
- AND 15 次元特徴量の重み付き合成スコアからティアを決定する
- AND signals.method は `distilled-features` である
- AND signals には learned classifier 由来の semantic labels と dimension ごとのスコアが含まれる
- AND signals.featureVersion は bundle の `feature_schema_version` から導出される

#### Scenario: API embedding backend is used for runtime classification

**Given** the feature classifier is loadable
**And** `embedding.mode` is `api`
**And** API embedding configuration resolves to a provider/base URL and model
**When** runtime prompt classification runs
**Then** kani MUST request embeddings from the configured API backend using the configured model
**And** the request MUST be bounded by `embedding.timeout_seconds`
**And** successful embedding prediction MUST feed the learned classifier before tier selection

#### Scenario: local embedding backend is used for runtime classification

**Given** the feature classifier is loadable
**And** `embedding.mode` is `local`
**And** `embedding.local_model` is configured
**When** runtime prompt classification runs
**Then** kani MUST compute embeddings through the local backend
**And** kani MUST NOT call the external embeddings API for that classification request
**And** successful local embedding prediction MUST feed the learned classifier before tier selection

#### Scenario: embedding backend is disabled

**Given** `embedding.mode` is `disabled`
**When** runtime prompt classification runs
**Then** kani MUST return the conservative default fallback: tier=MEDIUM, confidence=0.35, score=0.0
**And** signals.method MUST be `default`
**And** heuristic semantic labels MUST NOT be used as a runtime fallback

#### Scenario: embedding 呼び出しがタイムアウトする

- GIVEN 蒸留特徴量分類器は読み込めた
- AND runtime embedding 呼び出しが設定された timeout を超過する
- WHEN プロンプトを分類する
- THEN embedding 失敗として扱い、デフォルトフォールバック結果を返す: tier=MEDIUM, confidence=0.35, score=0.0
- AND signals.method は `default` である
- AND embedding timeout が routing 全体をブロックしない
- AND expected timeout fallback SHOULD be logged without a traceback-level exception stack

#### Scenario: embedding model identity mismatch is surfaced

**Given** the feature classifier bundle records an embedding model identity
**And** runtime embedding configuration resolves to a different model identity
**When** runtime classifier activation is checked or used
**Then** kani MUST surface the mismatch through diagnostics or warning logs
**And** kani MUST NOT silently present the learned classifier as fully healthy without noting the mismatch
