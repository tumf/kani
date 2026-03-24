# Use tiktoken for compaction token estimation

## Problem / Context

The current compaction token estimator uses a fixed ratio of 4 characters per token (`_CHARS_PER_TOKEN = 4` in `src/kani/compaction.py:35`). This ratio is tuned for English ASCII text and significantly underestimates token counts for CJK languages (Japanese, Chinese, Korean) where a single character often maps to 1-2 tokens.

Consequences:

- For Japanese-heavy conversations the actual token count can be 2-4x higher than the estimate.
- The `threshold_percent` and `trigger_percent` gates fire too late (or never), causing compaction to be skipped when it should have triggered.
- Token-savings telemetry reported via `X-Kani-Compaction-Saved-Tokens` is unreliable.

`tiktoken` is already declared as a project dependency (`pyproject.toml` line 20) but is not used in the compaction module.

## Proposed Solution

Replace the fixed-ratio estimator in `_estimate_tokens()` with a tiktoken-based implementation that resolves the encoding from the target model name. Fall back to `cl100k_base` when the model name is unknown.

Keep the function signature unchanged so callers (`try_sync_compaction`, `_resolve_compaction`, background worker) require no changes.

## Acceptance Criteria

- `_estimate_tokens()` uses tiktoken encoding when available.
- Model-name-to-encoding resolution is done once per request path, not per message.
- Fallback to `cl100k_base` when the model is unrecognized (no crash).
- Existing tests continue to pass; new tests cover CJK token estimation accuracy.
- No new dependencies (tiktoken is already present).

## Out of Scope

- Exact per-message token counting that includes OpenAI message framing overhead.
- Provider-specific tokenizer selection (e.g., Anthropic vs. OpenAI encodings).
