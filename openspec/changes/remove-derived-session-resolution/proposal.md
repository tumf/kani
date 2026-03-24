# Remove derived session resolution

## Problem / Context

The smart-proxy context compaction feature currently resolves session identity
via two modes:

1. **explicit** -- the client sends a configurable HTTP header (`X-Kani-Session-Id`).
2. **derived** -- when no header is present, kani hashes the model name together
   with a lightweight fingerprint of the first and last messages
   (`role[:8]:content[:64]`) to produce a deterministic session ID.

The derived mode is prone to **false-positive collisions**:

* Two independent conversations that share the same system prompt and happen to
  have an identical last user message (e.g. two users sending "hello") will hash
  to the same session ID.
* The `content[:64]` truncation means long messages that differ only after the
  64th character also collide.
* Message count is ignored entirely, so a 3-message conversation and a
  30-message conversation can collide.

When a collision occurs the wrong cached summary is applied, corrupting the
conversation context.

## Proposed Solution

Remove the derived fallback and split compaction behaviour into two tiers based
on whether a session ID is available:

| Capability | Session ID present (explicit) | No session ID |
|---|---|---|
| Sync compaction (inline) | Yes -- summary also persisted for future reuse | Yes -- summary generated and applied but **not** persisted |
| Cached summary reuse | Yes | No |
| Incremental summarization | Yes | No (full single-pass every time) |
| Background precompaction | Yes | No |
| Session state persistence | Yes | No |

This preserves the context-overflow safety net for all users (sync compaction
always fires when the threshold is exceeded) while making cache/background
features opt-in via an explicit header -- the intended workflow for service
developers who control the client.

## Acceptance Criteria

1. The `derived` resolution mode and `_message_structure_key` helper are removed.
2. When no explicit session header is provided, `resolve_session_id` returns
   `(None, "none")`.
3. Sync compaction (`inline` mode) works identically regardless of whether a
   session ID is present; the only difference is that the generated summary is
   not persisted when session ID is `None`.
4. Cache lookup (`cached` mode), incremental summarization, background
   precompaction scheduling, and session state upsert are all gated on
   `session_id is not None`.
5. Response header `X-Kani-Compaction-Session` is omitted when no session ID is
   resolved; `X-Kani-Compaction` still reflects the mode (`inline`, `skipped`,
   etc.).
6. `CompactionResult.session_mode` accepts `"none"` in addition to `"explicit"`.
7. All existing tests that assert derived behaviour are removed or updated;
   new tests cover the `session_id=None` inline path.
8. CI passes (ruff, pyright, pytest, build).

## Out of Scope

* Implementing an alternative automatic session derivation algorithm (e.g.
  Context Gateway-style first-user-message hashing). If desired in the future
  it should be proposed separately.
* Changes to routing, scoring, or any non-compaction proxy behaviour.
