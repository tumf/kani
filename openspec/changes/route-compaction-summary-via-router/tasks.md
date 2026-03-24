## Implementation Tasks

- [x] Task 1: Add `Router.resolve_model()` method to `src/kani/router.py` (verification: `uv run pyright src/kani/router.py` passes; new unit test in `tests/test_router.py` or `tests/test_compaction.py` confirms RoutingDecision is returned without scorer/log calls)
- [x] Task 2: Replace `SyncCompactionConfig.summary_model` with `summary_profile` in `src/kani/config.py` (verification: `uv run pyright src/kani/config.py` passes; existing `TestCompactionConfig` tests updated and pass)
- [x] Task 3: Replace Phase A model resolution in `proxy.py:534-556` with `_router.resolve_model()` call (verification: `uv run pytest tests/test_compaction.py -q` passes; `rg 'profiles\.get\("compress"\)' src/` returns zero matches in proxy.py Phase A block)
- [x] Task 4: Replace Phase B model resolution in `proxy.py:627-637` with `_router.resolve_model()` call (verification: `uv run pytest tests/test_compaction.py -q` passes; `rg 'profiles\.get\("compress"\)' src/` returns zero matches)
- [x] Task 5: Update `compaction_config` test fixture in `tests/test_compaction.py` to use `summary_profile` instead of defining a `compress` profile (verification: `uv run pytest tests/test_compaction.py -q` all pass)
- [x] Task 6: Update `config.example.yaml` to document `summary_profile` instead of `summary_model` (verification: comments in example yaml match new config field name)
- [x] Task 7: Run full CI suite (verification: `uv run ruff check src/ && uv run ruff format --check src/ tests/ && uv run pyright src/ && uv run pytest tests/ -q`)

## Future Work

- Update README.md compaction configuration section to reflect `summary_profile` change
- Consider adding deprecation warning if `summary_model` is detected in config (graceful migration)
