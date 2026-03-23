# Kani OpenSpec

このディレクトリは Kani プロジェクトの OpenSpec ベースラインです。

## 構造

```
openspec/
  specs/           # 現在の動作を記述したベースライン仕様
    proxy-api/     # OpenAI 互換プロキシ API
    routing/       # プロンプト分類とモデルルーティング
    config/        # YAML 設定の読み込み・バリデーション
    auth/          # API キー管理・認証ミドルウェア
    REVIEW.md      # レビューノート (信頼度分類)
  changes/         # 今後の変更提案 (change-driven development)
```

## ベースラインの使い方

`specs/` 配下の各 `spec.md` は、現在の Kani の動作を Requirement / Scenario 形式で記述しています。これらは現時点の source of truth です。

## 今後の変更フロー

ベースラインが確立された後、新しい機能変更やバグ修正は以下のフローで進めてください:

### 1. 変更提案の作成

```
openspec/changes/<change-id>/
  proposal.md    # 変更の目的・スコープ・影響範囲
  specs/         # 変更後の仕様 (差分)
  design.md      # 技術設計 (任意)
  tasks.md       # 実装タスクの分解 (任意)
```

### 2. proposal.md に含めるべき内容

- 変更の動機と目的
- 影響を受ける既存の spec (Requirement 単位)
- 新しい Requirement / Scenario の追加・変更・削除
- 後方互換性への影響
- テスト計画

### 3. レビューとマージ

1. proposal.md をレビューして承認
2. 実装を進める
3. 完了後、`specs/` 配下のベースラインを更新
4. `changes/<change-id>/` はアーカイブまたは削除

## Phase 2 拡張候補

以下のドメインは必要に応じて追加:

- **cli** — Click CLI コマンド群の仕様
- **dashboard** — 分析ダッシュボードとログインジェスト
- **logging** — JSONL ルーティングログ・実行ログ
- **training** — Agentic 分類器の訓練パイプライン
- **dirs** — XDG ディレクトリ解決ルール
