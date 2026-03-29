# Design: Fallback exponential backoff

## Summary

Introduce a process-local cooldown registry for retryable upstream failures so repeated requests avoid recently failing `model+provider` pairs for a bounded time window.

## Why this needs design

The change spans config, routing candidate selection, proxy fallback behavior, and operational logging. It also introduces durable-in-process state whose semantics must be consistent between route-time filtering and proxy-time outcome recording.

## Scope choice

This remains a single proposal because the behavior is tightly coupled:

- config adds tuning knobs for the same runtime feature
- routing must skip cooled primary candidates
- proxy must skip cooled fallback candidates and update state on success/failure

Shipping these separately would create inconsistent semantics.

## State model

Backoff state is keyed by `(model, provider)`.

Each entry should track at least:

- `failure_streak`
- `cooldown_until`

Recommended behavior:

- on retryable non-streaming failure: increment streak and set `cooldown_until`
- on success: clear cooldown and reset streak to zero
- on lookup: treat an entry as active only while `now < cooldown_until`

## Delay calculation

Use exponential growth with a max clamp:

`delay = min(initial_delay_seconds * multiplier^(failure_streak - 1), max_delay_seconds)`

This keeps early failures cheap while preventing rapid hammering of an unhealthy upstream.

## Routing integration

`Router.route()` currently filters candidates by required capabilities and then chooses a primary candidate. Cooldown filtering should happen on the already capability-filtered candidate list before round-robin selection finalizes the primary.

This preserves existing capability semantics while preventing immediate reuse of recently failing pairs.

## Proxy integration

`_try_with_fallbacks()` should:

1. record retryable failure for the selected primary after a retryable response
2. skip fallback candidates that are currently cooled down
3. record retryable failure for fallback attempts that also return retryable responses
4. record success for whichever candidate eventually succeeds

Streaming behavior remains unchanged: no new cross-request backoff semantics are required for stream execution in this proposal.

## Failure policy when all candidates are cooled down

If cooldown filtering leaves no eligible candidate, the system should not bypass cooldown as a last resort. It should return the current failure path normally.

This avoids turning a provider incident into a tight retry loop.

## Observability

Add warning/info logs for:

- cooldown applied after retryable failure
- candidate skipped because cooldown is active
- streak reset after success

Logging failures must remain non-blocking.
