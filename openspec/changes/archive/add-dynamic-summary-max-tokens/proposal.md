# Add dynamic summary max_tokens

## Problem / Context

`generate_summary()` in `src/kani/compaction.py:176` uses a hardcoded `max_tokens: 512` for all summary generation requests. This causes two problems:

1. **Short middle regions**: when only a few hundred tokens of conversation are being summarized, 512 tokens is wasteful and the summary may pad or hallucinate filler.
2. **Long middle regions**: when thousands of tokens of conversation are being summarized, 512 tokens is insufficient and critical facts, decisions, and constraints are lost from the handoff summary.

The summary quality directly determines how well the model can continue the conversation after compaction, making this a high-leverage improvement.

## Proposed Solution

Compute `max_tokens` dynamically as a configurable ratio of the estimated middle-region token count, with a floor and ceiling:

```
max_tokens = clamp(middle_tokens * ratio, min_summary_tokens, max_summary_tokens)
```

Default values:
- `ratio`: 0.25 (25% of middle region)
- `min_summary_tokens`: 128
- `max_summary_tokens`: 1024

Expose `summary_ratio`, `min_summary_tokens`, and `max_summary_tokens` as optional fields in `SyncCompactionConfig` so operators can tune the trade-off between compression aggressiveness and information retention.

## Acceptance Criteria

- `generate_summary()` computes `max_tokens` dynamically based on the middle-region token estimate.
- The ratio, floor, and ceiling are configurable via `SyncCompactionConfig`.
- Default behavior produces shorter summaries for short middles and longer summaries for long middles.
- Existing tests pass; new tests cover boundary conditions (very short middle, very long middle, custom config).

## Out of Scope

- Adaptive ratio based on content complexity or semantic density.
- Per-model summary token budget tuning.
