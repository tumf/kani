---
change_type: implementation
priority: high
dependencies: []
references:
  - https://github.com/tumf/kani/issues/4
  - src/kani/proxy.py
  - src/kani/config.py
  - tests/
---

# Sanitize Reasoning Message Fields

**Change Type**: implementation

## Problem / Context

Some providers expose message-level reasoning fields, specifically `messages[].reasoning_content`. If conversation history containing this field is routed to a different upstream provider/model that rejects unknown message fields, the proxy can fail with upstream validation errors. This is a payload compatibility problem at the routed proxy boundary, not a prompt difficulty classification signal.

## Proposed Solution

Introduce routed proxy-layer sanitization for `messages[].reasoning_content` before sending routed requests upstream. The sanitizer should remove unsupported `reasoning_content` fields from `messages` for incompatible selected upstreams, while preserving `reasoning_content` only when support is explicitly declared by repo-local model/provider compatibility metadata defined in existing config surfaces, such as a model_rules- or provider-level flag chosen by this change.

Pass-through requests are left unchanged by this feature and are not sanitized by routed-request compatibility logic.

The routing classifier must continue to classify based on prompt/content difficulty and must not force tier escalation solely because prior messages contain `reasoning_content`.

## Acceptance Criteria

1. Routed primary upstream requests strip unsupported `messages[].reasoning_content` before proxying.
2. Routed fallback attempts apply the same sanitization for the fallback model/provider, not stale primary compatibility assumptions.
3. `messages[].reasoning_content` is preserved only when the selected model/provider explicitly declares support through the repo-local compatibility flag defined by this change.
4. Pass-through requests are unchanged by this feature and have a test documenting that routed-request sanitization does not apply to them.
5. Routing tier selection does not change solely because conversation history contains `reasoning_content`.

## Explicit Completion Conditions

- Tests reproduce a routed request containing `messages[].reasoning_content` and assert the incompatible upstream payload omits it.
- Tests cover fallback payload sanitization with a fallback provider/model.
- Tests cover an explicitly supported model/provider retaining the field.
- Tests document that pass-through requests are unchanged by this feature.
- Source code keeps sanitization in proxy/payload adaptation paths, not scorer tier logic.
- Relevant local verification commands complete successfully for proxy tests and Python checks.

## Out of Scope

- Importing third-party sanitizer code.
- Sanitizing arbitrary provider-specific message fields beyond `messages[].reasoning_content`.
- Hardcoding external provider assumptions without repo-local configuration support.
- Rewriting reasoning control injection generally beyond what is needed for message-field compatibility.
- Changing routing thresholds or tier escalation behavior.
