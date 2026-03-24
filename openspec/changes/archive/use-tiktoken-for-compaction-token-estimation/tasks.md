## Implementation Tasks

- [x] Refactor `_estimate_tokens()` in `src/kani/compaction.py` to accept an optional `model` parameter and use `tiktoken.encoding_for_model()` with `cl100k_base` fallback (verification: `uv run pytest tests/test_compaction.py -q`)
- [x] Cache the resolved tiktoken `Encoding` object per model name in a module-level dict to avoid repeated initialization (verification: second call with same model reuses cached encoder)
- [x] Thread the `model` string from the request body through `_resolve_compaction()` in `src/kani/proxy.py` into `_estimate_tokens()` calls (verification: `uv run pytest tests/test_compaction.py -q`)
- [x] Add tests in `tests/test_compaction.py::TestEstimateTokens` for CJK text, English text, mixed text, and unknown-model fallback (verification: `uv run pytest tests/test_compaction.py::TestEstimateTokens -q`)
- [x] Run full CI checks: `uv run ruff check src/ && uv run ruff format --check src/ tests/ && uv run pyright src/ && uv run pytest tests/ -q`

## Future Work

- Per-provider tokenizer mapping (Anthropic, Mistral, etc.) when kani gains multi-provider token counting.
- Exact message-framing token overhead calculation per OpenAI spec.
