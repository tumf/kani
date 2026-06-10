# Constitution

This document defines the design constraints that Kani must not violate.
It is intentionally minimal. Implementation details belong in the individual specs.

## 1. Preserve OpenAI API compatibility

- Kani must remain usable as a drop-in OpenAI-compatible proxy.
- Clients should be able to switch their `base_url` and `model` without changing their SDK or request shape.
- API responses, errors, model listing, health checks, and routing diagnostics must preserve stable, client-consumable shapes.

## 2. Keep routing deterministic and auditable

- Runtime routing decisions must be reproducible for the same input and the same configuration.
- Routing decisions must expose enough information to audit why a model and provider were selected.
- The classifier, features, scoring method, and calibration strategy may evolve, but changes must preserve tier meaning and fallback safety.
- Uncertain or failed routing decisions must converge to explicit fallbacks or safe defaults, not silently drift to unsupported, unexpectedly expensive, or higher-risk models.

## 3. Fail closed on capability and input-limit safety

- Kani must not select a candidate that lacks a capability required by the request.
- Kani must not select a candidate whose known input limit is smaller than the estimated request input.
- If no configured candidate can safely satisfy the request, Kani must return a clear routing error instead of choosing an unsafe final fallback.
- Unknown metadata may remain eligible for backward compatibility, but known-incompatible metadata must be authoritative.

## 4. Fail fast on ambiguous or unsafe configuration

- Invalid, ambiguous, or silently ignored configuration must be rejected or surfaced clearly.
- Legacy aliases may exist for compatibility, but they must not create ambiguous behavior when the primary configuration surface is also present.
- Secrets must be supplied through environment-aware configuration, not hardcoded values.
- Optional operational features may degrade gracefully, but core configuration errors must not become hidden runtime behavior changes.

## 5. Preserve client intent

- Kani must respect explicit client-provided fields and must not rewrite them in ways that change their meaning.
- Provider-specific adaptation must be the minimum transformation needed to preserve compatibility.
- Transformations, omissions, retries, fallbacks, and compaction decisions should be observable whenever practical.
- Even when Kani changes the upstream target or payload for safety, compatibility, or context management, it must preserve the intent of the original client request.
