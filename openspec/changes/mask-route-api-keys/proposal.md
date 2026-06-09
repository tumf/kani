---
change_type: implementation
priority: medium
dependencies: []
references:
  - openspec/specs/routing/spec.md
  - src/kani/cli.py
  - src/kani/router.py
---

# Mask API keys in `kani route` CLI output

**Change Type**: implementation

## Problem

`kani route` prints the full `RoutingDecision` as JSON via `decision.model_dump()`, which includes `api_key` fields resolved from environment variables. This leaks secrets into script output, logs, or shell history.

`kani config` already masks API keys with `"***"`. `kani route` does not.

## Proposed Solution

Redact `api_key` values in the routing decision output before serialization.

The `RoutingDecision` model (defined in `src/kani/router.py`) includes `api_key: str | None` on the top-level object and on each fallback entry. Redaction should mask any non-empty key value before `.model_dump()`.

Two options:
- Option A: Override `model_dump()` (or use `model_dump(mode="json")` + post-processing) to mask api_key fields.
- Option B: Strip/mask `api_key` from the JSON dict after dump.

Option B is simpler and avoids model-level changes.

## Acceptance Criteria

- `kani route "hello"` output contains `"api_key": "***"` instead of the real key value, both for the top-level entry and for fallback entries.
- `kani config` behavior is unchanged (already masked).
- Unmasked API key values are never printed by the CLI.

## Explicit Completion Conditions

- Edit `src/kani/cli.py` around line 74 where `decision.model_dump()` is serialized. Add a helper that walks the dict and replaces any value for the key `"api_key"` with `"***"`, recursing into lists/dicts.
- Run `uv run pytest tests/ -q` to verify no regressions.
- Manually confirm: `uv run kani route "test"` shows `"api_key": "***"` in JSON output.

## Out of Scope

- Changing the `RoutingDecision` Pydantic model.
- Masking API keys in HTTP response bodies or proxy logs (handled separately in proxy layer if needed).
- `kani keys` commands (already handle key names/prefixes only).
