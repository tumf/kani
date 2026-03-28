# Add primary round-robin routing per tier

## Premise / Context

- ユーザー要望は「`primary` に複数記述を許可し、ラウンドロビンで選択したい」。
- 追加要件として「選ばれた primary が失敗した場合、fallback 群から同一候補を外して重複リトライしない」方針が明示された。
- 統合方針として、既存の `fallback: null` 受理改善は本提案へ取り込み、別提案は削除して一本化する。
- 現行実装では `TierModelConfig.primary` は単一値のみで、`Router.route()` は常に単一 primary を選択する (`src/kani/config.py`, `src/kani/router.py`)。
- フォールバック実行は `decision.fallbacks` を順に試すだけで重複除外はない (`src/kani/proxy.py`)。
- `fallback: null` は YAML で `null` 解釈されると strict validation で失敗しうるため、tier fallback 専用の正規化要件が必要。

## Problem

現在の設定では tier ごとに primary を 1 つしか定義できず、同格モデル間の負荷分散や利用分散をプロファイル内で表現できない。また、将来 `primary` と `fallback` に同一候補が共存した場合、同一リクエスト内で同じモデル・プロバイダを重複再試行するリスクがあり、遅延・コスト・障害時ノイズを増やす。

## Proposed Solution

`TierModelConfig.primary` を後方互換で拡張し、単数 (`str | ModelEntry`) に加えて複数 (`list[str | ModelEntry]`) を受け付ける。`Router` は `profile+tier` 単位のプロセス内カウンタで primary 候補をラウンドロビン選択する。選択された primary が失敗して fallback に入る際は、`model+provider` が同一の候補を fallback 試行列から除外し、同一リクエスト内の重複リトライを防止する。あわせて `profiles.*.tiers.*.fallback` に限り `null` を `[]` に正規化してから検証し、設定互換性を改善する。`primary` が単数の場合は現行挙動を維持する。

## Acceptance Criteria

- 設定で各 tier の `primary` に複数候補（文字列または model/provider オブジェクト配列）を記述できる。
- 同一 `profile+tier` に対する連続リクエストで primary 選択がラウンドロビンする（A→B→A...）。
- `primary` が単数の既存設定では、モデル選択・プロバイダ解決・フォールバック解決の挙動が従来と同じ。
- primary 失敗後の fallback 試行では、当該リクエストで既に primary として失敗した同一 `model+provider` 候補が除外される。
- fallback リストに重複がある場合でも、実行時は重複試行せず設定順を保った一意列として試行される。
- `profiles.*.tiers.*.fallback: null` を受理し、空 fallback として扱う。
- `fallback` 以外の無関係な `null` 値は従来どおり自動正規化せず、必要に応じてバリデーションエラーとなる。
- 関連テスト（router/proxy/config）と lint/typecheck が通る。

## Out of Scope

- ラウンドロビンカウンタの永続化（再起動後も継続する DB 保存など）。
- プロセス間での分散協調（複数ワーカー間で厳密な共通 RR 状態を持つこと）。
- フォールバックの自動生成ルール変更（未選択 primary の自動注入など）。
