---
change_type: implementation
priority: high
dependencies:
  - replace-routing-cascade-with-distilled-features
references:
  - src/kani/router.py
  - src/kani/scorer.py
  - src/kani/training_data.py
  - openspec/specs/routing/spec.md
---

# Use conversation context for routing classification

**Change Type**: implementation

## Problem / Context

現在の routing 分類入力は最後の user message をそのまま scorer に渡している。これでは、会話の前段で積み上がった制約、目的、依頼対象、system prompt の方針が分類入力から落ちる。

distilled feature classifier は prompt の意図・複雑度・agentic 性を feature 化するため、最後の user message 単体では誤判定しやすい。特に以下のケースで問題が大きい。

- 前段の会話で定義された制約や目的を、最後の短い追記が省略している
- 「はい」「続けて」「それで」など短い継続メッセージが、実際には高文脈タスクの継続である
- 学習データ生成時に runtime と異なる入力粒度を使うと、蒸留対象と本番推論の意味空間がずれる

## Proposed Solution

- routing classifier の入力を最後の user message から、会話コンテキストを反映した単一の classification text に変更する
- classification text は少なくとも、関連する system prompt、直近の user requests、必要な assistant context を一貫したルールで含める
- runtime scoring と distilled training data generation は同じ classification text builder を共有する
- ログには raw prompt だけでなく、分類に実際に使った context-aware text かその preview / metadata を残す
- 短い継続メッセージでも、会話全体の依頼継続として分類できるようにする

## Acceptance Criteria

- `Router` は最後の user message 単体ではなく、会話文脈を反映した classification input を scorer に渡す
- classification input の構築ルールは deterministic で、runtime と training data generation の両方で再利用される
- 短い user follow-up が、直前の会話文脈を含めた場合に feature classifier で高文脈タスクとして扱える
- routing logs には、分類に使った文脈情報を後続分析・再学習に十分な粒度で残す
- routing spec baseline は「最後の user message を使う」前提から、context-aware classification input を使う前提へ更新される

## Out of Scope

- 会話全履歴の無制限投入
- 会話要約専用の別 LLM を runtime で呼ぶこと
- classifier 本体の feature schema 変更
- context compaction 機能との統合最適化
