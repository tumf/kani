# Design: Add configurable runtime embedding

## Overview

Runtime scoring currently calls an external API via the OpenAI Python client on every `Scorer.classify()`. This change adds operator-selectable embedding backends (api/local/disabled) with configurable timeout.

## Embedding Backend Architecture

```
config.yaml:embedding
    ├── mode=api → _resolve_runtime_embedding_client() → OpenAI(base_url, api_key).embeddings.create()
    ├── mode=local → LocalEmbeddingBackend → lazy import → in-process embedding
    └── mode=disabled → raise RuntimeError → default fallback
```

All backends return `np.ndarray[float32]` with the same shape as `DistilledFeatureClassifier.embedding_dim`. Failures converge to default fallback.

## Config Changes

`EmbeddingConfig` adds three fields:

| Field | Type | Default | Notes |
|---|---|---|---|
| `mode` | `Literal["api", "local", "disabled"]` | `"api"` | When unset, existing `enabled: false` normalizes to `disabled` for backward compat. |
| `timeout_seconds` | `float` | `5.0` | Runtime embedding call timeout. Constrained `> 0`. |
| `local_model` | `str` | `""` | Used when `mode=local`. Lazily imported; missing dependency → fallback. |

`enabled` field is preserved for backward compatibility. Internal normalization: `enabled=false` → `mode=disabled`.

## Runtime Embedding Resolution

```python
def _resolve_embedding_backend(cfg: EmbeddingConfig) -> EmbeddingBackend:
    match cfg.effective_mode:
        case "api":
            return ApiEmbeddingBackend(...)
        case "local":
            return LocalEmbeddingBackend(model_name=cfg.local_model)
        case "disabled":
            raise RuntimeError("embedding is disabled")
```

`DistilledFeatureClassifier._embed_text()` uses `cfg.timeout_seconds` for the API backend and local backend alike, wrapping both in the existing `ThreadPoolExecutor` timeout pattern.

## Timeout Behavior Change

Current: `TimeoutError` propagates with full stack trace via `log.exception()`.  
Proposed: timeout logged as `log.warning("Runtime embedding timed out, using default fallback")` without traceback. The exception is still raised and caught by `Scorer.classify()`, but `log.exception` is replaced with `log.warning` for the specific `TimeoutError` path.

## Compatibility Check

At `DistilledFeatureClassifier.load()` time, if the bundle's `embedding_model` does not match the resolved runtime `EmbeddingConfig.model` (or `.local_model` for local mode), emit a warning. Dimension mismatch remains a hard error during prediction.

## Training Side

`src/kani/feature_training.py` records the effective model identity in the bundle. For local embedding mode, the model identity string must match exactly between training and runtime.

## Rejected Alternatives

- **Embedding result caching**: deferred to follow-up. Caching adds complexity around cache invalidation and prompt uniqueness that should be evaluated after backend choice stabilizes.
- **Removing sklearn entirely**: out of scope. The sklearn classifier works; the problem is the embedding input source.
- **Auto-detecting local model from pip packages**: fragile. Explicit `local_model` config is predictable.
