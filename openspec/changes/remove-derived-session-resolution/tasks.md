## Implementation Tasks

- [ ] Task 1: Remove derived fallback from `resolve_session_id` (verification: `resolve_session_id(messages, model="x")` with no explicit header returns `(None, "none")`; `uv run pyright src/kani/compaction_store.py` passes)
- [ ] Task 2: Delete `_message_structure_key` helper function from `compaction_store.py` (verification: `rg _message_structure_key src/` returns no hits)
- [ ] Task 3: Update `_resolve_compaction` in `proxy.py` to gate DB operations on `session_id is not None` -- skip `upsert_session`, `mark_stale_summaries`, `get_ready_summary`, `get_latest_ready_summary_for_session`, `save_snapshot`, `enqueue_summary`, and background scheduling when session is None (verification: inline compaction still triggers at threshold with no session header; `uv run pytest tests/test_compaction.py -q` passes)
- [ ] Task 4: Update `_resolve_compaction` so that inline summary generation + `try_sync_compaction` execute regardless of session_id presence (verification: test with session_id=None shows `mode="inline"` when threshold exceeded)
- [ ] Task 5: Update `_compaction_headers` in `proxy.py` to omit `X-Kani-Compaction-Session` when `session_id` is None (verification: unit test asserts header absent for `session_id=None` result)
- [ ] Task 6: Update `CompactionResult.session_mode` docstring/comment to reflect `"none"` replacing `"derived"` (verification: `rg 'derived' src/kani/compaction` returns no hits outside comments explaining removal)
- [ ] Task 7: Remove or update derived-mode tests in `tests/test_compaction.py` (verification: no test references `derived` mode; `uv run pytest tests/test_compaction.py -q` passes)
- [ ] Task 8: Add tests for session_id=None inline compaction path (verification: `uv run pytest tests/test_compaction.py -q -k no_session` passes)
- [ ] Task 9: Run full CI suite (verification: `uv run ruff check src/ && uv run ruff format --check src/ tests/ && uv run pyright src/ && uv run pytest tests/ -q && uv build` all pass)

## Future Work

- Consider adding an alternative automatic session derivation (e.g. first-user-message hash) as an opt-in mode in a future proposal.
