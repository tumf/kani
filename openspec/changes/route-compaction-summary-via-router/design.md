# Design: route compaction summary via Router

## Summary

Remove the manual provider/model resolution from compaction and replace it with a thin `Router.resolve_model()` helper. This eliminates the hardcoded `compress` profile dependency and the duplicated resolution logic in `proxy.py`.

## Architecture

### 1. New Router method: `resolve_model()`

Add to `Router` class in `src/kani/router.py`:

```python
def resolve_model(
    self,
    *,
    profile: str | None = None,
    tier: str = "SIMPLE",
) -> RoutingDecision:
```

Behavior:
- Resolve profile name: use `profile` if given, else `self.config.default_profile`.
- Look up `ProfileConfig` and `TierModelConfig` for the requested tier.
- Resolve primary model and provider (reuse existing `_resolve_provider_name()` and `_lookup_provider()`).
- Build fallback entries (reuse existing logic).
- Return `RoutingDecision` with dummy score/confidence/signals (not applicable for internal resolution).
- **Do NOT** call `_classify()` (no scorer).
- **Do NOT** call `RoutingLogger.log_decision()` (no log pollution).

This method shares all the private helpers with `route()` but skips the two expensive/side-effectful operations.

### 2. Config model change

In `SyncCompactionConfig` (`src/kani/config.py`):

- Remove: `summary_model: str = ""`
- Add: `summary_profile: str = ""`

When `summary_profile` is empty, `proxy.py` passes `None` to `resolve_model()`, which falls through to `default_profile`.

### 3. Proxy integration

In `_resolve_compaction()` (`src/kani/proxy.py`):

**Phase A** (current lines 534-556, ~23 lines) becomes:

```python
decision = _router.resolve_model(
    profile=sync_cfg.summary_profile or None,
    tier="SIMPLE",
)
```

Then pass `decision.model`, `decision.base_url`, `decision.api_key` to `generate_summary()`.

**Phase B** (current lines 627-637, ~11 lines) becomes the same single call.

### 4. Compaction module

`generate_summary()` signature in `src/kani/compaction.py` is unchanged — it already accepts `summary_model`, `base_url`, `api_key` as parameters. The caller changes, not the callee.

`BackgroundCompactionWorker.schedule()` and `_run()` signatures are also unchanged.

### 5. Loop safety

`resolve_model()` is a pure synchronous method on `Router` that reads config and returns a dataclass. It never makes HTTP requests, never calls compaction code, and never enters the FastAPI request lifecycle. Loop is structurally impossible.

## Risks and mitigations

### Config migration

Risk: Existing `config.yaml` files with `summary_model` will fail Pydantic validation.

Mitigation: This is an intentional breaking change. The field is undocumented and not used in production configs. Update `config.example.yaml` and note in CHANGELOG.

### Default profile as fallback

Risk: If `default_profile` has no `SIMPLE` tier, `resolve_model()` will fail.

Mitigation: Reuse `_fallback_tier()` in `resolve_model()` so it degrades gracefully through adjacent tiers, matching existing `route()` behavior.
