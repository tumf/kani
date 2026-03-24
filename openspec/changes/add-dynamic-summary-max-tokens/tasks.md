## Implementation Tasks

- [ ] Add `summary_ratio: float = 0.25`, `min_summary_tokens: int = 128`, `max_summary_tokens: int = 1024` fields to `SyncCompactionConfig` in `src/kani/config.py` (verification: `uv run pyright src/ && uv run pytest tests/test_compaction.py::TestCompactionConfig -q`)
- [ ] Add a `_compute_summary_max_tokens(middle_tokens: int, ratio: float, floor: int, ceiling: int) -> int` helper in `src/kani/compaction.py` (verification: unit tests for boundary values)
- [ ] Update `generate_summary()` in `src/kani/compaction.py` to accept and use the dynamic max_tokens instead of the hardcoded 512 (verification: `uv run pytest tests/test_compaction.py -q`)
- [ ] Thread the new config fields from `_resolve_compaction()` in `src/kani/proxy.py` through to `generate_summary()` and the background worker `schedule()` call (verification: `uv run pytest tests/test_compaction.py -q`)
- [ ] Add tests in `tests/test_compaction.py` for: short middle (hits floor), long middle (hits ceiling), default ratio, custom ratio override (verification: `uv run pytest tests/test_compaction.py -q -k summary_max_tokens`)
- [ ] Update `config.example.yaml` to document the new fields under `sync_compaction` (verification: manual inspection)
- [ ] Run full CI checks: `uv run ruff check src/ && uv run ruff format --check src/ tests/ && uv run pyright src/ && uv run pytest tests/ -q`

## Future Work

- Adaptive ratio based on content complexity scoring.
- Dashboard visibility for summary token budget utilization.
