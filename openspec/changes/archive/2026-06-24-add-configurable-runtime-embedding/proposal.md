---
change_type: implementation
priority: high
dependencies: []
references:
  - openspec/CONSTITUTION.md
  - openspec/specs/config/spec.md
  - openspec/specs/routing/spec.md
  - src/kani/config.py
  - src/kani/scorer.py
  - src/kani/feature_training.py
---

# Add configurable runtime embedding

**Change Type**: implementation

## Premise / Context

- Runtime routing currently calls the distilled feature classifier when `Router.route()` classifies a prompt.
- The classifier turns prompt text into embeddings, then uses the trusted sklearn bundle to predict semantic dimensions.
- Existing config supports `embedding.model`, `embedding.provider`, `embedding.base_url`, `embedding.api_key`, and `embedding.enabled`, but timeout is hardcoded and local embedding is not available.
- The constitution forbids heuristic runtime semantic classification; failed classifier paths must converge to explicit safe defaults.
- The desired change is to let operators choose external API embedding model/provider and optionally use a local embedding backend without making routing unstable.

## Problem / Context

Routing quality depends on the learned feature classifier, but the embedding call is in the request-time critical path. A fixed runtime timeout and API-only backend make the router sensitive to network latency, provider outages, and unclear training/runtime model mismatches.

Operators need explicit control over the embedding backend, model identity, and timeout while preserving deterministic, auditable routing behavior.

## Proposed Solution

Add a configurable embedding backend surface:

- `embedding.mode`: `api`, `local`, or `disabled`
- `embedding.timeout_seconds`: bounded request-time timeout for runtime embedding calls
- `embedding.local_model`: local model identifier/path used when `mode=local`
- clear validation for unsupported modes, invalid timeouts, missing API provider details, and missing local runtime dependencies
- runtime diagnostics that show the effective embedding backend/model without exposing secrets

Keep learned classifier semantics unchanged: successful embedding + classifier prediction returns `distilled-features`; any unavailable, disabled, timed-out, or failed embedding path returns the conservative default fallback.

## Acceptance Criteria

- Operators can configure external API embedding provider/model and timeout in `config.yaml`.
- Operators can configure local embedding mode without calling an external API at route time.
- `embedding.mode=disabled` explicitly puts runtime classification into default fallback mode.
- Invalid embedding mode or invalid timeout is rejected during config validation.
- Training and runtime verification detect or surface embedding model/dimension mismatches before silently using an incompatible classifier bundle.
- Runtime embedding timeouts log a concise warning rather than noisy exception stack traces for expected degraded fallback.
- No heuristic keyword/substr/rule-based semantic fallback is introduced.

## Explicit Completion Conditions

- `src/kani/config.py` defines and validates the new embedding fields with tests covering valid and invalid configurations.
- `src/kani/scorer.py` resolves API/local/disabled embedding modes and preserves default fallback on unavailable or failed embeddings.
- Local embedding mode has mock-based unit coverage that proves routing classification does not call the OpenAI embeddings API.
- API embedding mode has unit coverage proving configured provider, model, and timeout are used.
- Training/runtime compatibility checks cover model identity and embedding dimension mismatch behavior.
- `kani doctor` or equivalent diagnostics expose effective embedding backend/model/timeout without secrets.
- Strict OpenSpec validation passes for this change.

## Out of Scope

- Reintroducing heuristic runtime semantic classification.
- Replacing the sklearn classifier architecture.
- Shipping a large local embedding model inside the repository.
- Requiring real external embedding credentials in default tests.
