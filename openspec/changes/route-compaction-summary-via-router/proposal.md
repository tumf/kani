# Route compaction summary generation via Router

## Problem / Context

The compaction subsystem currently resolves which LLM to use for summary generation by manually looking up provider configs and hardcoding a dependency on a `compress` profile name. This creates three problems:

1. **Hardcoded profile dependency** — `proxy.py` references `_config.profiles.get("compress")` in two places (Phase A line 546, Phase B line 630). If the operator does not define a `compress` profile, compaction silently skips with no clear error.
2. **Duplicated provider resolution** — Both Phase A and Phase B independently assemble `summary_model`, `base_url`, and `api_key` from raw config, duplicating ~34 lines of identical logic that the Router already encapsulates.
3. **Bypassed routing infrastructure** — The summary LLM call does not benefit from the Router's provider lookup, fallback chain, or profile/tier model resolution. Any future provider changes require updating compaction code separately.

## Proposed Solution

Replace the manual model/provider resolution in compaction with a lightweight `Router.resolve_model()` helper that reuses the existing profile-to-tier-to-provider resolution path without running the scorer or writing routing logs.

Key changes:

- Add `Router.resolve_model(profile, tier)` — resolves a `RoutingDecision` (model, base_url, api_key, provider, fallbacks) for a given profile and tier, skipping scorer classification and RoutingLogger.
- Replace `SyncCompactionConfig.summary_model` with `SyncCompactionConfig.summary_profile` — operators specify a profile name (e.g. `"compress"`, `"eco"`) instead of a raw model ID. Empty string falls back to `default_profile`.
- Eliminate the duplicated model resolution blocks in `proxy.py` Phase A (lines 534-556) and Phase B (lines 627-637), replacing each with a single `_router.resolve_model()` call.
- Pass the resolved model/base_url/api_key from the `RoutingDecision` to `generate_summary()` and `BackgroundCompactionWorker.schedule()`.

This ensures compaction summary generation uses the same provider infrastructure as all other kani requests, with zero risk of infinite loop since `resolve_model()` never enters the HTTP request/compaction code path.

## Acceptance Criteria

- `Router.resolve_model(profile=..., tier=...)` returns a valid `RoutingDecision` without invoking the scorer or writing routing logs.
- Compaction summary generation in both Phase A and Phase B uses `resolve_model()` for model/provider resolution.
- The `compress` profile string is no longer hardcoded anywhere in the codebase.
- `SyncCompactionConfig.summary_model` is replaced by `SyncCompactionConfig.summary_profile`.
- When `summary_profile` is empty, the `default_profile` is used.
- Existing compaction behavior (skip when disabled, fail-closed on errors) is preserved.
- All existing tests pass; new tests cover `resolve_model()`.

## Out of Scope

- Changing the compaction algorithm itself (token estimation, hierarchical summarization, dynamic max_tokens).
- Adding fallback retry logic for summary generation failures.
- Modifying the `generate_summary()` prompt or max_tokens.
- Dashboard or telemetry changes.
