# Add Capability-Aware Routing

## Problem / Context

現在のルーターはプロンプトの **難易度 tier** と **agentic スコア** のみでモデルを選択する。
リクエストが要求する LLM 能力（画像入力・ツールコール・JSON 出力等）をモデルが持っているかは検証されない。

その結果、以下のケースで上流プロバイダがエラーを返す：

- `image_url` コンテンツブロックを含むリクエストが Vision 非対応モデルに転送される
- `tools` / `functions` フィールドを含むリクエストがツールコール非対応モデルに転送される
- `response_format.type = "json_object"` のリクエストが JSON モード非対応モデルに転送される

## Proposed Solution

### 1. `config.yaml` に `model_capabilities` セクションを追加

モデル名の **前方一致プレフィックス** と能力セットを宣言するリスト形式：

```yaml
model_capabilities:
  - prefix: "claude-"
    capabilities: [tools, vision, json_mode]
  - prefix: "gpt-5"
    capabilities: [tools, json_mode]
  - prefix: "google/gemini"
    capabilities: [tools, vision, json_mode]
```

### 2. `KaniConfig` に `model_capabilities` フィールドを追加（`config.py`）

```python
class ModelCapabilityEntry(BaseModel):
    prefix: str
    capabilities: list[str]

class KaniConfig(BaseModel):
    # ...
    model_capabilities: list[ModelCapabilityEntry] = Field(default_factory=list)
```

`Router` がプレフィックス前方一致で能力セットを引くヘルパーを持つ：

```python
def _get_model_capabilities(self, model_id: str) -> set[str]:
    for entry in self.config.model_capabilities:
        if model_id.startswith(entry.prefix):
            return set(entry.capabilities)
    return set()  # 未記載 = 能力なし（安全側）
```

### 3. `router.route()` に `required_capabilities` 引数を追加（`router.py`）

- 候補選択時（primary / fallback 両方）に能力フィルタリングを実施
- tier 内で capable 候補がゼロ → 次 tier へ escalate（既存 `_fallback_tier_name` を活用）
- 全 tier 枯渇 → `CapabilityNotSatisfiedError` を raise

### 4. `proxy.py` でリクエストから要求能力を検出

`/v1/chat/completions` ハンドラで `_detect_required_capabilities(body)` を呼び出し、
`router.route()` に渡す。

### 5. `RoutingDecision` に `required_capabilities` フィールドを追加

ログ・デバッグ用途。

## Acceptance Criteria

1. `image_url` コンテンツを含むリクエストは、`vision` 能力を持つモデルにのみルーティングされる
2. `tools` / `functions` フィールドを含むリクエストは、`tools` 能力を持つモデルにのみルーティングされる
3. `response_format.type` が `json_object` / `json_schema` のリクエストは、`json_mode` 能力を持つモデルにのみルーティングされる
4. `model_capabilities` が空またはモデルが未記載の場合、全候補が能力なしとみなされ要求能力があれば `CapabilityNotSatisfiedError` になる
5. `required_capabilities` が空（{}）の場合、既存のルーティングロジックと完全互換
6. tier 内に capable 候補がない場合、上位 tier に自動 escalate する
7. 全 tier に capable 候補がない場合、400 エラー相当の `CapabilityNotSatisfiedError` を raise し、proxy が適切な JSON エラーを返す
8. ラウンドロビン選択は capable 候補のみを対象に行われる

## Out of Scope

- 新しい能力種別（`streaming`、`function_calling_parallel` 等）の追加
- 能力の自動検出（プロバイダ API への問い合わせ）
- 能力ミスマッチのリトライ（フォールバックのみ対応）
