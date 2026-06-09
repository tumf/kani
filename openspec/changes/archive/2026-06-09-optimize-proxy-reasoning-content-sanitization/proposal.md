---
change_type: implementation
priority: medium
dependencies: []
references:
  - src/kani/proxy.py
  - tests/test_proxy_reload.py
  - openspec/specs/proxy-api/spec.md
---

# Optimize Proxy Reasoning Content Sanitization

**Change Type**: implementation

## Problem / Context

`sanitize_reasoning_content` performs a full `copy.deepcopy` on every message before determining whether any `reasoning_content` key is present. On the proxy hot path, large chat or multimodal payloads routed to providers that do not support reasoning pay unnecessary CPU and memory cost even when no sanitization is needed.

## Proposed Solution

Scan for affected dict messages first, shallow-copy the body and only copy individual messages that require mutation, then return the original body early when no reasoning fields are present.

## Acceptance Criteria

- Messages without `reasoning_content` are returned unchanged without a deep copy.
- Messages with `reasoning_content` still have that key removed from the upstream payload.
- Existing behavior, response shape, and header behavior are unchanged.
- The `_get_model_reasoning_content_support` docstring precedence language is no longer asserted in tests.

## Explicit Completion Conditions

- `src/kani/proxy.py` `sanitize_reasoning_content` no longer calls `copy.deepcopy` when no affected messages exist, and only shallow-copies individual messages that contain `reasoning_content`.
- `tests/test_proxy_reload.py` asserts correctness of provider resolution precedence without asserting docstring text.
- Verification commands pass: `uv run pytest tests/test_proxy_reload.py -q`, `uv run ruff check src/`, `uv run ruff format --check src/ tests/`, `uv run pyright src/`.

## Out of Scope

- Changing the set of supported provider reasoning styles.
- Adding new provider-specific payload fields beyond existing `reasoning_content` handling.
