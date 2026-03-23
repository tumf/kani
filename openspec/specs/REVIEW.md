# OpenSpec Baseline Review Notes

生成日: 2026-03-23

## 対象ドメイン (Phase 1)

| ドメイン | ファイル | ステータス |
|---------|--------|-----------|
| proxy-api | `openspec/specs/proxy-api/spec.md` | Draft |
| routing | `openspec/specs/routing/spec.md` | Draft |
| config | `openspec/specs/config/spec.md` | Draft |
| auth | `openspec/specs/auth/spec.md` | Draft |

## 信頼度分類

### テスト/ドキュメントで確認済み

以下の動作はテストまたはドキュメントにより確認済み:

- **Routing: 3層カスケード分類** — `test_scorer.py` で embedding→LLM エスカレーション、全失敗時のデフォルトフォールバックがカバーされている
- **Routing: LLM 分類器のタイムアウト/不正応答** — `test_llm_classifier.py` で 2秒タイムアウト、不正応答の None 返却がカバーされている
- **Routing: プロンプト切り詰め 500文字** — `test_llm_classifier.py::TestLLMClassifierUnit::test_prompt_truncation` で確認
- **Routing: Agentic 分類の発動条件** — `test_scorer.py::TestAgenticClassification` で SIMPLE のみ、classify_agentic フラグの動作が確認
- **Routing: ログプレビュー 200文字** — `test_llm_classifier.py::TestRoutingLogger` で確認
- **Routing: ClassificationResult の形状安定性** — `test_scorer.py::TestResultShape` で確認
- **Routing: signals 辞書の公開/内部分離** — `test_router_logging.py` で signal_details が log_decision に渡されつつ公開 signals は変更されないことを確認
- **Auth: API キーライフサイクル** — `test_api_keys.py` で生成/検証/一覧/名前削除/プレフィックス削除の全パスがカバー
- **Auth: 認証ミドルウェア** — `test_api_keys_proxy.py` でキー未設定時の通過、health 免除、有効/無効キーがカバー
- **Auth: CLI キー管理** — `test_api_keys_cli.py` で add/list/remove がカバー
- **Config: strict モードの例外** — `test_cli.py::TestConfigExceptions` で ConfigNotFoundError, ConfigIncompleteError が確認
- **Config: init コマンド** — `test_cli.py::TestInitCommand` で作成/上書き拒否/force がカバー

### コードから推測 (要レビュー)

以下の動作はコードから読み取ったが、テストで直接カバーされていない:

- **Proxy: フォールバックは 5xx のみ** — `proxy.py` の `_try_with_fallbacks` 実装から推測。4xx でリトライしない動作のテストは見当たらない
- **Proxy: ストリーミングレスポンスのリトライ不可** — コード上は StreamingResponse が 5xx でもリトライされない。テストでは未カバー
- **Proxy: stream_options.include_usage 注入** — コードで確認。テストでは未カバー
- **Proxy: URL 構築 (/v1 末尾の正規化)** — `proxy.py` のロジックから推測。テストでは未カバー
- **Config: 環境変数未設定時の空文字列置換** — `resolve_env` の `os.environ.get(var, "")` から推測
- **Config: deep merge オーバーライド** — コードから推測。統合テストでは未カバー
- **Routing: agentic_score > 0.6 での SIMPLE→MEDIUM 昇格** — `router.py` のコードから推測。テストでは未カバー
- **Routing: ティアフォールバック (下方向優先)** — `router.py::_fallback_tier` から推測。テストでは未カバー
- **Dashboard: /dashboard の認証状態** — コード上は `_AUTH_EXEMPT` に含まれていない。README.DASHBOARD.md では免除と記載。不一致の可能性あり

### 要注意事項 (潜在的バグ/設計上の曖昧さ)

- **Dashboard 認証不一致**: `_AUTH_EXEMPT` パスに `/dashboard` が含まれていないが、ドキュメントでは認証免除と記載されている可能性。意図的な設計かバグか要確認
- **LLM 分類器の固定信頼度 0.8**: LLM 分類器は常に confidence=0.8 を返す。実際の LLM の不確実性を反映しないが、これは意図的な設計判断と思われる
- **Agentic 昇格閾値 0.6 のハードコード**: `router.py` で `agentic_score > 0.6` がハードコードされている。設定可能にすべきか要検討
- **embedding min_confidence のデフォルト値**: Scorer は 0.65、Agentic は 0.7 と異なる閾値。これらは設定ファイルから変更できない
- **HTTPクライアントのタイムアウト設定**: connect=10s, read=300s がハードコード。長時間推論モデルには適切だが、設定可能にする余地あり

## 未カバー領域 (Phase 2 候補)

| ドメイン | 説明 |
|---------|------|
| cli | Click CLI コマンド群 (serve, route, config, init, keys) |
| dashboard | SQLite インジェスト、統計、HTML レンダリング |
| logging | JSONL ルーティングログ、実行ログ |
| training | Agentic 分類器の訓練パイプライン |
| dirs | XDG ディレクトリ解決 |
