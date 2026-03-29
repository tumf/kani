# Add exponential backoff for fallback failures

## Problem / Context

Kani currently retries retryable upstream failures by moving from the selected primary model to configured fallback models within the same request. This handles a single failing request well, but it does not remember that a specific `model+provider` pair is currently unhealthy.

When a model is rate-limited or returning repeated 5xx responses, subsequent requests can still route back to the same unhealthy candidate immediately. That causes avoidable repeated failures, extra latency, and noisy fallback cascades under provider incidents.

## Proposed Solution

Add a process-local exponential backoff mechanism for retryable fallback failures keyed by `model+provider`.

Recommended behavior:

1. When a non-streaming upstream request returns a retryable failure (`429` or `5xx`), record a failure event for that exact `model+provider` pair.
2. Apply an exponential cooldown window to that pair using configurable parameters under `smart_proxy`.
3. While a pair is in cooldown, exclude it from future primary candidate selection and fallback candidate execution.
4. Reset that pair's failure streak when a later request to the same `model+provider` succeeds.
5. If cooldown filtering leaves no candidate for the current request, fail normally rather than bypassing the cooldown.

The initial implementation should keep state in process memory only. Restarting the server clears the cooldown state.

## Acceptance Criteria

- Retryable failures from a specific `model+provider` cause that pair to enter a cooldown window that grows exponentially on consecutive retryable failures.
- Cooldown filtering applies to both primary candidate selection and fallback execution for later requests.
- A successful request to a cooled-down pair after its cooldown expires resets its failure streak for future backoff calculation.
- Cooldown state is keyed by `model+provider`, so the same model on a different provider is unaffected.
- Streaming requests continue to avoid fallback retries as they do today; this proposal does not add cross-request backoff behavior to streaming execution.
- Configuration exists for enabling/disabling the feature and tuning initial delay, multiplier, and maximum delay.
- Logs make cooldown application and cooldown-based candidate skipping observable without breaking request handling.
- Routing/proxy tests cover cooldown growth, cooldown-based skipping, success reset, and provider-specific isolation.

## Out of Scope

- Persisting cooldown state across process restarts or sharing it across multiple server instances.
- Adding dashboard or public API endpoints for cooldown inspection.
- Changing existing retryability rules beyond the already retryable non-streaming `429` / `5xx` failures.
