## MODIFIED Requirements

### Requirement: Primary ラウンドロビン選択

ルーターは `profile+tier` 単位で primary 候補をラウンドロビン選択しなければならない (SHALL)。ただし cooldown 中の `model+provider` 候補は選択対象から除外しなければならない (SHALL)。

#### Scenario: 同一 profile+tier で連続リクエスト

- GIVEN `primary` 候補列が `[A, B]` の `profile+tier` がある
- WHEN 同一 `profile+tier` に対して連続でルーティングを行う
- THEN 選択 primary は `A -> B -> A -> ...` の順で回転する

#### Scenario: cooldown 中の primary 候補を除外する

- GIVEN primary 候補列に `A`, `B` がある
- AND `A` に対応する `model+provider` が cooldown 中である
- WHEN その `profile+tier` をルーティングする
- THEN システムは `A` を選択対象から除外する
- AND cooldown 中でない候補から primary を選択する

#### Scenario: 同一 model でも provider が違えば別 cooldown として扱う

- GIVEN 同じ model ID を使う候補が複数 provider に存在する
- AND そのうち一方の `model+provider` だけが cooldown 中である
- WHEN ルーティング候補を評価する
- THEN システムは cooldown 中の組だけを除外する
- AND 他 provider の同一 model 候補は引き続き選択可能である
