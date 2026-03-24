# Add hierarchical compaction summarization

## Problem / Context

The current compaction algorithm in `_compact_messages()` (`src/kani/compaction.py:47`) treats the entire middle region as a flat block and replaces it with a single summary on every request. This has two problems as conversations grow longer:

1. **Redundant re-summarization**: each compaction pass re-summarizes the full middle region from scratch, including portions that were already summarized in a previous pass. This wastes LLM calls and latency.
2. **Progressive information loss**: repeated full re-summarization of growing conversations causes a lossy cascade — each pass discards more detail from earlier turns, and critical facts established early in the conversation erode over multiple compaction cycles.

A hierarchical approach preserves prior summaries as stable context and only summarizes the new unsummarized portion, then merges the two. This is analogous to how incremental log compaction works in databases.

## Proposed Solution

Introduce an incremental summarization mode alongside the existing single-pass mode:

1. When a prior summary already exists for the session (from Phase B cache or a previous Phase A pass), treat it as a stable prefix.
2. Identify the **new unsummarized middle** — messages between the end of the prior summary's coverage and the start of the protected tail.
3. Summarize only the new middle.
4. Merge the prior summary and the new summary into a combined handoff block (either by concatenation with a separator, or by a short merge-LLM call if the combined size exceeds a threshold).

This reduces per-request LLM work and improves information retention across multiple compaction cycles.

## Acceptance Criteria

- When a prior summary exists for the session, compaction summarizes only the delta (new unsummarized messages).
- The merged summary preserves key facts from both the prior summary and the new delta.
- When no prior summary exists, behavior is identical to the current single-pass algorithm.
- The prior summary's message coverage boundary is tracked in `compaction_store` so the delta can be computed.
- Existing tests pass; new tests cover: first-pass (no prior), second-pass (with prior), merge behavior.

## Out of Scope

- Multi-level hierarchical trees (3+ levels of nested summaries). This proposal covers two levels: prior + delta.
- Semantic importance scoring to selectively preserve high-value turns.
- Summary quality verification or fact-checking.
