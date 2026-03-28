## Implementation Tasks

- [x] 1. Add config schema for capability prefixes in `src/kani/config.py` (verification: `uv run pyright src/` passes and config model accepts `model_capabilities` entries from `config.yaml`)
- [x] 2. Add required-capability detection in `src/kani/proxy.py` for `image_url`, `tools`/`functions`, and `response_format.type` (verification: request handling paths in `src/kani/proxy.py` pass new proxy tests for capability extraction)
- [x] 3. Add capability-aware candidate filtering and tier escalation to `src/kani/router.py` using prefix matching from config (verification: router tests cover capable primary selection, capable fallback selection, tier escalation, and no-capable-model failure)
- [x] 4. Add a router/proxy error path for unsatisfied capability requirements and return structured JSON error output (verification: proxy tests assert 400-style JSON response when no configured model satisfies required capabilities)
- [x] 5. Add `required_capabilities` to `RoutingDecision` and routing logs where applicable (verification: router tests and any logging assertions remain green)
- [x] 6. Update `config.yaml` with `model_capabilities` entries for currently configured model families using prefix rules (verification: config loads successfully via `uv run kani config`)
- [x] 7. Add or update tests in `tests/` for prefix matching, capability filtering, and backwards compatibility when no capabilities are required (verification: `uv run pytest tests/ -q -k capability` or equivalent targeted routing/proxy tests pass)
- [x] 8. Run repo checks after implementation (verification: `uv run ruff check src/`, `uv run ruff format --check src/ tests/`, `uv run pyright src/`, `uv run pytest tests/ -q`, and `uv build` all pass)

## Future Work

- 必要に応じて `vision`, `tools`, `json_mode` 以外の能力種別を追加する
- 将来的にプロバイダ側メタデータと `model_capabilities` の整合性チェックを導入する
