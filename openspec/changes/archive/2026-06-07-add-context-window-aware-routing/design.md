# Design: Context-window-aware routing

## Scope

This change adds a routing-time guard that prevents known too-small model candidates from being selected for long requests. It does not change prompt classification, compaction policy, provider discovery, or upstream request/response shapes.

## Candidate Metadata

`ModelEntry` should carry optional `context_window_tokens`. String model entries remain supported and are treated as having an unknown context window.

The router currently passes candidates around as `(model_id, provider_name)` tuples. The implementation may either introduce an internal candidate dataclass or preserve a metadata lookup alongside the existing tuple shape. The key requirement is that provider precedence and backward-compatible helper behavior remain intact.

## Filtering Order

Recommended routing order:

1. Resolve profile and initial tier.
2. Classify the request and apply existing agentic tier promotion.
3. Resolve primary candidates for the tier.
4. Filter by required capabilities.
5. Estimate prompt tokens for the request.
6. Filter candidates with configured `context_window_tokens` lower than the estimate.
7. If no eligible primary candidate remains, evaluate fallback candidates and then higher tiers using the same capability and context filters.
8. Apply fallback-backoff cooldown filtering.
9. Select via the existing per-profile+tier round-robin from remaining eligible primary candidates.

This preserves the user's core requirement: a small model with a known insufficient context window is not selected for long context.

## Unknown Context Windows

Unknown context windows stay eligible for backward compatibility. This avoids breaking existing configurations that use plain string model IDs or have not yet annotated every model. Operators who need strict avoidance should annotate the small models with `context_window_tokens`.

## All Candidates Too Small

The minimal behavior is to avoid choosing known-too-small candidates when an alternative exists. If every annotated candidate is too small and there is no unknown candidate, the router should not introduce a new public error type in this change. Existing compaction/upstream handling remains responsible for the final outcome.

## Verification Strategy

Tests should stub classification to a deterministic tier and use message content large enough to exceed a small candidate threshold. They should prove that routing decisions depend on `context_window_tokens`, not only on candidate ordering or round-robin state.
