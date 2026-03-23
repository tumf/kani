# Add smart proxy context compaction

## Problem / Context

kani is currently attractive as a smart router and OpenAI-compatible proxy, but it does not yet reduce context pressure for long-running conversations. Every request is routed and proxied as-is, so clients pay the full prompt cost on each turn and eventually hit model context limits without assistance from the proxy layer.

The target direction is to evolve kani toward a smarter proxy that can apply opt-in context reduction strategies, starting with:

1. request-time compaction of oversized message histories (Phase A), and
2. session-aware background precompaction with cached summaries (Phase B).

This proposal intentionally scopes implementation to A+B while keeping the architecture aligned with a later Context Gateway-class smart proxy, including user-switchable features rather than a single hard-wired behavior.

## Proposed Solution

Introduce a configurable smart-proxy context compaction subsystem in kani with the following behavior:

- Add a new context compaction configuration surface so operators can independently enable or disable request-time compaction and session-aware background precompaction.
- Add lightweight session tracking keyed by an explicit request header first, with deterministic fallbacks when the client does not provide a session identifier.
- Persist session snapshots, token usage, compaction job state, and ready summaries in a local SQLite store under kani's XDG data directory.
- When a routed request exceeds a configured threshold, optionally compact the middle portion of `messages` before proxying upstream (Phase A).
- When a session crosses a configured precompaction threshold, enqueue background summarization so a later request can reuse a precomputed summary with minimal added latency (Phase B).
- Keep all new behavior transparent and opt-in: if disabled, unavailable, or failed, kani must preserve current passthrough routing behavior.
- Expose compaction outcomes through structured headers/logging/dashboard metrics so operators can observe hit rate, savings, and failure modes.

## Acceptance Criteria

- kani accepts configuration for smart-proxy context compaction with separate switches for synchronous request-time compaction and session-aware background precompaction.
- For oversized routed requests, kani can replace the middle span of `messages` with a generated handoff summary while preserving protected head/tail turns and maintaining valid OpenAI-compatible message ordering.
- kani can persist session snapshots and token metadata, trigger asynchronous precompaction after threshold crossing, and reuse a ready summary on a later request for the same session.
- If compaction is disabled, missing configuration, or fails at runtime, kani continues to route and proxy requests without breaking existing behavior.
- Operators can inspect whether compaction ran, was reused from cache, or was skipped via headers, logs, and dashboard-visible metrics.

## Out of Scope

- Phantom tools such as `expand_context` or tool-search injection.
- Tool schema pruning / tool discovery optimization.
- Non-OpenAI request shapes beyond the proxy's currently supported chat-completions surface.
- Full Context Gateway equivalence in this change; this proposal only establishes the A+B foundation and toggle model needed to reach that later.
