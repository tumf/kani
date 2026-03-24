## Implementation Tasks

- [ ] Add `covered_message_count INTEGER DEFAULT 0` column to `compaction_summaries` table in `src/kani/compaction_store.py::init_db()` and update `enqueue_summary()` / `update_summary()` to read/write it (verification: `uv run pytest tests/test_compaction.py::TestSummaryLifecycle -q`)
- [ ] Add `merge_threshold: int = 768` field to `SyncCompactionConfig` in `src/kani/config.py` (verification: `uv run pyright src/`)
- [ ] Implement `_compact_messages_incremental()` in `src/kani/compaction.py` that accepts an optional prior summary and its covered count, computes the delta middle, and returns the compacted list (verification: new unit tests)
- [ ] Implement `_merge_summaries(prior: str, new: str, merge_threshold: int, ...) -> str` in `src/kani/compaction.py` with concatenation path and merge-summarize path (verification: new unit tests)
- [ ] Update `_resolve_compaction()` in `src/kani/proxy.py` to look up prior summary coverage and pass it to the incremental compaction path (verification: `uv run pytest tests/test_compaction.py -q`)
- [ ] Update `BackgroundCompactionWorker._run()` in `src/kani/compaction.py` to use incremental summarization and update `covered_message_count` on completion (verification: `uv run pytest tests/test_compaction.py -q`)
- [ ] Add tests: first-pass with no prior summary (same as current behavior), second-pass with prior summary (delta-only), merge via concatenation, merge via LLM call, snapshot-hash mismatch fallback (verification: `uv run pytest tests/test_compaction.py -q -k hierarchical`)
- [ ] Run full CI checks: `uv run ruff check src/ && uv run ruff format --check src/ tests/ && uv run pyright src/ && uv run pytest tests/ -q`

## Future Work

- Multi-level hierarchy (3+ nested summary tiers) for extremely long-running sessions.
- Semantic importance scoring to selectively preserve high-value turns before summarization.
- Summary quality verification (fact-checking the merged output against source messages).
