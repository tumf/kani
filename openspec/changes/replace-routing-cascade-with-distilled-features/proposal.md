---
change_type: implementation
priority: high
dependencies: []
references:
  - src/kani/scorer.py
  - src/kani/router.py
  - src/kani/logger.py
  - src/kani/training_data.py
  - openspec/specs/routing/spec.md
---

# Replace routing cascade with distilled feature classifier

**Change Type**: implementation

## Problem / Context

現在の routing 分類は embedding tier 分類器 → LLM fallback → default のカスケードと、SIMPLE ティア時のみの独立 agentic 分類で構成されている。これは以下の問題を持つ。

- ティア分類と agentic 判定が別系統で、説明可能性が低い
- 本番ルーティングで LLM fallback に依存し、推論遅延と外部依存を持つ
- tier 直分類器は後から重みや判断理由を再解釈しにくい
- 既存 routing logs を feature 学習データへ活用する導線が弱い

今回の変更では、tier 直分類と独立 agentic 分類を廃止し、`tokenCount` + 14 semantic dimensions の 15 次元特徴量に基づく distilled classifier に置き換える。

## Proposed Solution

- 既存の tier direct embedding classifier / LLM classifier / agentic classifier を廃止する
- `tokenCount` は deterministic に算出し、残り 14 項目は multi-output learned semantic classifier で `low|medium|high` を推定する
- 学習用ラベルは routing logs の prompt 群に対して LLM が 14 項目を構造化アノテーションして生成する
- 本番ルーティングは embedding + learned feature model + weighted synthesis のみで tier と agentic score を決定する
- `agenticTask` dimension を既存 `agentic_score` と統合し、agentic profile の SIMPLE→MEDIUM 昇格はその統合 score で継続する
- classification result / routing log には feature-based の判定根拠を残す

## Acceptance Criteria

- runtime routing は tier direct embedding classifier と LLM fallback を使用せず、15 次元特徴量ベース分類のみで tier を返す
- runtime routing は独立した agentic classifier を使用せず、`agenticTask` dimension 由来の score を `agentic_score` として返す
- classifier training pipeline は routing logs から教師データを生成し、semantic dimensions を蒸留学習できる
- classification result は tier, confidence, agentic_score に加えて feature-based explanation を安定して返す
- routing logs は feature-based method と dimension payload を記録し、後続学習に再利用できる
- routing spec baseline は旧カスケード仕様から feature-distillation 仕様へ更新される

## Out of Scope

- 日本語 first-class 最適化
- 本番時の LLM feature 判定
- 旧分類器との並行運用
- 重み最適化の自動探索やオンライン再学習
