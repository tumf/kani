# Design: hierarchical compaction summarization

## Summary

Extend the compaction algorithm from single-pass full-region summarization to incremental two-level summarization. Prior summaries are treated as stable context; only new unsummarized messages are sent to the LLM, and results are merged.

## Architecture

### 1. Coverage tracking

Add a `covered_message_count` integer column to the `compaction_summaries` table in `compaction_store.py`. This records how many messages (from the start of the middle region) the summary covers. When computing the delta for a subsequent compaction, skip the first `covered_message_count` messages of the middle region.

### 2. Delta identification

In `_compact_messages()` (or a new `_compact_messages_incremental()` variant):

1. Load the most recent `ready` summary for the session + snapshot lineage.
2. If a prior summary exists with `covered_message_count = K`, the new middle is `messages[head_end + K : tail_start]`.
3. If the new middle is empty (no new messages since last summary), reuse the prior summary as-is.
4. Otherwise, summarize only the new middle.

### 3. Merge strategy

Two strategies, selected by the combined token size:

- **Concatenation** (default, when `prior_tokens + new_summary_tokens < merge_threshold`): join with a `---` separator and a `[Continued]` label. No additional LLM call.
- **Merge-summarize** (when combined size exceeds `merge_threshold`): send both summaries to the LLM with a merge prompt to produce a single condensed summary. This bounds the growth of the summary block over many cycles.

`merge_threshold` defaults to 768 tokens and is configurable.

### 4. Request path changes

The `_resolve_compaction()` function in `proxy.py` gains a step between session resolution and compaction:

1. Look up prior summary for the session.
2. If found and still valid (not stale), pass it and its `covered_message_count` to the compaction function.
3. After compaction, update `covered_message_count` in the stored summary.

### 5. Background worker changes

The background worker's `_run()` method follows the same incremental logic: load prior summary, summarize delta, merge, store with updated coverage.

## Risks and mitigations

### Coverage drift

Risk: `covered_message_count` gets out of sync if the client sends a different message history than expected.

Mitigation: validate by comparing the snapshot hash. If the hash doesn't match the stored lineage, fall back to full single-pass summarization.

### Merge quality

Risk: concatenated summaries become incoherent over many cycles.

Mitigation: the merge-summarize path kicks in when combined size exceeds the threshold, preventing unbounded growth. The merge prompt instructs the LLM to deduplicate and condense.
