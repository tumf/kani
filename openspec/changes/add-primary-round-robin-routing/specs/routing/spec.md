## MODIFIED Requirements

### Requirement: ティア定義

分類結果に対応する tier 設定は primary 候補を 1 件以上保持しなければならない (SHALL)。

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

### Requirement: フォールバック試行の重複除外

フォールバック試行列は同一リクエスト内で重複試行を行わないよう正規化されなければならない (SHALL)。

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
