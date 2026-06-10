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

The `RoutingDecision` model and each `FallbackEntry` (defined in `src/kani/router.py`) include `api_key: str` fields. Redaction should mask non-empty key values after `.model_dump()` and leave empty-string key values empty so unset providers remain distinguishable from configured secrets.

Two options:
- Option A: Override `model_dump()` (or use `model_dump(mode="json")` + post-processing) to mask api_key fields.
- Option B: Strip/mask `api_key` from the JSON dict after dump.

Option B is simpler and avoids model-level changes.

## Acceptance Criteria

- `kani route "hello"` output contains `"api_key": "***"` instead of the real key value, both for the top-level entry and for fallback entries with non-empty keys.
- Empty API key values remain empty strings rather than being converted to a fake secret marker.
- `kani config` behavior is unchanged (already masked).
- Unmasked API key values are never printed by the CLI.

## Explicit Completion Conditions

- Edit `src/kani/cli.py` around line 74 where `decision.model_dump()` is serialized. Add a helper that walks the dumped dict and replaces non-empty string values for the key `"api_key"` with `"***"`, recursing into lists/dicts.
- Add coverage in `tests/test_cli.py` proving non-empty top-level and fallback `api_key` values are masked while empty strings remain empty.
- Run `uv run pytest tests/test_cli.py -q` and `uv run pytest tests/ -q` to verify no regressions.

## Out of Scope

- Changing the `RoutingDecision` Pydantic model.
- Masking API keys in HTTP response bodies or proxy logs (handled separately in proxy layer if needed).
- `kani keys` commands (already handle key names/prefixes only).
