# Design: smart proxy context compaction

## Summary

This change turns kani from a stateless routing proxy into a selectively stateful smart proxy for context reduction. The immediate goal is to ship two switchable behaviors:

- Phase A: request-time compaction of oversized chat histories.
- Phase B: session-aware background precompaction with reusable cached summaries.

The design deliberately keeps the public API OpenAI-compatible while adding internal state, queueing, and observability needed for future Context Gateway-class features.

## Goals

- Reduce prompt tokens and context-window pressure for long-running routed conversations.
- Keep the default path safe: when compaction is off or unavailable, current kani behavior must remain unchanged.
- Make each capability independently switchable so operators can enable only the strategies they trust.
- Reuse existing kani patterns where possible: FastAPI handlers stay thin, config remains YAML-driven, and analytics continue to flow through SQLite-backed dashboard ingestion.

## Non-Goals

- Full parity with Context Gateway in this change.
- Provider-specific compaction request emulation.
- Phantom tools or tool-schema optimization.

## Architecture

### 1. Config surface

Add a top-level config section such as `smart_proxy.context_compaction` with sub-sections for:

- `enabled`
- `sync_compaction.enabled`
- `sync_compaction.threshold_percent`
- `sync_compaction.protect_first_n`
- `sync_compaction.protect_last_n`
- `sync_compaction.summary_model` or provider override
- `background_precompaction.enabled`
- `background_precompaction.trigger_percent`
- `background_precompaction.max_concurrency`
- `background_precompaction.summary_ttl_seconds`
- `session.header_name` (default `X-Kani-Session-Id`)

Separate switches are required so operators can run:

- neither feature,
- only Phase A,
- only Phase B, or
- both together.

### 2. Session resolution

For routed requests, kani should resolve a stable session key in this order:

1. explicit configured header, default `X-Kani-Session-Id`
2. request metadata field if present and supported
3. deterministic fallback hash derived from model family + normalized message structure

The explicit header is the preferred path because precompaction is only useful when multiple requests map to the same session record.

### 3. Durable state

Store compaction state in SQLite under kani's data directory, separate from but adjacent to the existing dashboard database. A dedicated DB avoids coupling operational queue state to analytics ingestion.

Suggested tables:

- `compaction_sessions`
  - `session_id`
  - `profile`
  - `last_request_id`
  - `latest_snapshot_hash`
  - `latest_prompt_tokens`
  - `latest_total_tokens`
  - `updated_at`
- `compaction_snapshots`
  - `snapshot_hash`
  - `session_id`
  - `messages_json`
  - `prompt_tokens`
  - `created_at`
- `compaction_summaries`
  - `summary_id`
  - `session_id`
  - `snapshot_hash`
  - `status` (`queued`, `running`, `ready`, `failed`, `stale`)
  - `summary_text`
  - `estimated_tokens_saved`
  - `error_message`
  - `created_at`
  - `updated_at`

### 4. Request path

`src/kani/proxy.py` remains the orchestration point.

Proposed flow for routed requests:

1. parse request body
2. resolve routing decision
3. resolve session key and load compaction state if enabled
4. estimate current prompt size using request body and, when available, previous measured usage
5. if Phase A is enabled and the request exceeds the synchronous threshold, compact before upstream proxying
6. proxy upstream
7. record returned usage
8. if Phase B is enabled and usage crosses the precompaction trigger, enqueue or refresh a summary job

If a ready summary already exists for the current snapshot hash, kani may use the cached summary instead of generating a new one inline.

### 5. Compaction algorithm

Phase A and B should share the same message reduction strategy.

Core rules:

- protect the first N turns and the last N turns
- summarize only the middle region
- keep role ordering valid for OpenAI-compatible requests
- avoid partial removal that would corrupt message structure
- if safe compaction cannot be guaranteed, skip compaction and proxy unchanged

The summary payload should be a factual handoff block optimized for continuation, not an end-user summary.

### 6. Background precompaction

Start with an in-process async worker or bounded task manager owned by the FastAPI lifespan. This is sufficient for the current single-process Docker Compose deployment and keeps implementation small.

Worker behavior:

- accepts deduplicated jobs keyed by `session_id + snapshot_hash`
- refuses duplicate in-flight jobs
- marks jobs stale if a newer snapshot supersedes them
- writes ready or failed status back to SQLite
- never blocks the foreground request path on job completion

Future external worker extraction remains possible if deployment topology changes.

### 7. Observability

Operators need to see whether the smart-proxy layer is helping.

Add headers such as:

- `X-Kani-Compaction`: `off|skipped|inline|cached|failed`
- `X-Kani-Compaction-Session`: resolved session mode (`explicit|metadata|derived`)
- `X-Kani-Compaction-Saved-Tokens`: best-effort estimated savings

Also add structured log fields and dashboard ingestion support for:

- compaction attempts
- cache hits
- queued background jobs
- ready summaries
- failures
- estimated token savings

## Rollout plan

### Step 1

Land config models, session resolution, and SQLite state layer behind disabled-by-default flags.

### Step 2

Land Phase A inline compaction and tests for safe message rewriting.

### Step 3

Land Phase B background queueing and cached summary reuse.

### Step 4

Expose telemetry in headers/dashboard and document operator guidance.

## Risks and mitigations

### Session mismatch

Risk: derived session IDs produce low cache-hit rates.

Mitigation: document `X-Kani-Session-Id` as the preferred integration path and expose the session resolution mode in headers/logs.

### Message corruption

Risk: naive middle truncation can break OpenAI-compatible message ordering or future tool-calling behavior.

Mitigation: centralize boundary selection and fail closed by skipping compaction when structure is unsafe.

### Background churn

Risk: repeated requests generate redundant summaries.

Mitigation: deduplicate by `session_id + snapshot_hash`, mark stale summaries, and bound worker concurrency.

### Operational opacity

Risk: token savings are hard to trust without visibility.

Mitigation: emit explicit headers/logs/dashboard metrics for every decision path, including skips and failures.
