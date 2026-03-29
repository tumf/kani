## MODIFIED Requirements

### Requirement: フォールバック

プライマリモデルが retryable failure を返した場合、フォールバックモデルに順次試行しなければならない (SHALL)。また、retryable failure を返した `model+provider` は後続リクエストで一時的に再試行抑止されなければならない (SHALL)。

#### Scenario: プライマリモデルの 5xx エラー (非ストリーミング)

- GIVEN ルーティング決定にフォールバックモデルが定義されている
- AND リクエストが非ストリーミングである
- WHEN プライマリモデルのバックエンドが 5xx ステータスを返す
- THEN 次のフォールバックモデルのバックエンドに同じリクエストを送る
- AND すべてのフォールバックが失敗するまで順次試行する

#### Scenario: 429 は retryable failure として cooldown 対象になる

- GIVEN 非ストリーミングの upstream リクエストが特定の `model+provider` に送信される
- WHEN upstream が 429 を返す
- THEN システムはその `model+provider` を retryable failure として扱う
- AND その `model+provider` に cooldown を設定する

#### Scenario: cooldown 中の fallback 候補を再試行しない

- GIVEN fallback 候補列に cooldown 中の `model+provider` が含まれる
- WHEN fallback 試行列を実行する
- THEN システムはその候補をスキップする
- AND cooldown 中でない次の候補があればそちらを試行する

#### Scenario: 全 fallback 候補が cooldown 中である

- GIVEN 非ストリーミング request の primary が retryable failure を返す
- AND 残る fallback 候補がすべて cooldown 中である
- WHEN システムが fallback 実行可否を判定する
- THEN cooldown を破って再試行しない
- AND 最後の retryable error を返す
