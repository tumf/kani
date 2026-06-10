---
change_type: hybrid
priority: medium
dependencies: []
references:
  - openspec/specs/proxy-api/spec.md
  - openspec/specs/config/spec.md
  - src/kani/proxy.py
  - src/kani/config.py
  - tests/test_proxy_reload.py
---

# Harden reasoning_content compatibility logic and precedence

**Change Type**: hybrid

## Problem / Context

Kani recently introduced provider-specific reasoning-content compatibility controls via `model_rules[].supports_reasoning_content`. The implementation in `src/kani/proxy.py` added three new functions:

- `_get_model_reasoning_content_support` — prefix/provider-based model rules lookup
- `_supports_reasoning_content` — fallback chain: model rules → provider config → `False`
- `_sanitize_reasoning_content_for_candidate` — shallow-copy removal of `reasoning_content` when unsupported

The OCR review of `main..develop` identified four real concerns:

1. **Scoring precedence is undocumented and unintuitive.** `_get_model_reasoning_content_support` scores `(1 if entry.provider else 0, 0 if entry.prefix == "*" else len(entry.prefix))`. This means a provider-specific rule with a wildcard prefix (e.g. `{prefix: "*", provider: "dummy"}`) will always beat a highly specific provider-agnostic rule (e.g. `{prefix: "sonnet-4-20250514"}`). This is consistent with `_get_model_reasoning_style`'s scoring, but the impact on `supports_reasoning_content` is more consequential because an unexpected `False` result strips a field that may be needed.

2. **Unknown provider silently fail-closed with no warning.** `_supports_reasoning_content` falls through to `return bool(provider_cfg and ...)` which returns `False` for unknown providers. This is correct behavior (fail-closed), but operators configuring routing for providers they expect to support reasoning content get no diagnostic.

3. **Shallow copy aliasing risk in `_sanitize_reasoning_content_for_candidate`.** The function copies `body` with `dict(body)` and messages with `dict(msg)`, but untouched message dicts are shared with the original. If any downstream code mutates message contents after sanitization, the original `body` could be unexpectedly aliased.

4. **Test helper `_config_text` newline sensitivity.** Both `provider_body` and `model_rules` fragments are concatenated directly into YAML strings. A caller passing a fragment without a trailing newline can produce malformed YAML like `...api_key: "x"profiles:`.

## Proposed Solution

### 1. Document and test scoring precedence

- Add a docstring to `_get_model_reasoning_content_support` explicitly describing the precedence: provider-matching rules always win over provider-agnostic rules, even if the provider-agnostic rule has a longer prefix.
- Add a test case for wildcard-provider-vs-specific-prefix precedence.

### 2. Warn on unknown provider in fallback

- Add a `logging.warning` call when `provider_name` is not found in `runtime.config.providers` and neither model rules nor provider config resolved the support flag. This helps operators spot misconfigurations.

### 3. Deep-copy messages in sanitizer

- Replace the shallow-copy path in `_sanitize_reasoning_content_for_candidate` with `copy.deepcopy` for each message dict, ensuring complete isolation from the original body.

### 4. Fix test helper newline sensitivity

- Add trailing newline normalization inside `_config_text` for both `provider_body` and `model_rules_extra` fragments.

## Acceptance Criteria

1. `_get_model_reasoning_content_support` docstring explicitly states that provider-matching rules take precedence over prefix-length.
2. `_sanitize_reasoning_content_for_candidate` uses `copy.deepcopy` per message, verified by checking that mutating the returned messages list does not mutate the original input body's messages.
3. `_supports_reasoning_content` emits a warning log when neither model rules nor provider config resolve the flag for a known provider, verified by capturing `caplog` in a unit test.
4. `_config_text` helper in tests produces valid YAML regardless of whether caller-provided fragments end with a newline.
5. New test cases covering wildcard-provider-vs-specific-prefix scoring are present in `tests/test_proxy_reload.py`.

## Explicit Completion Conditions

1. **Source change**: `src/kani/proxy.py` updated with deep-copy in sanitizer, warning log in fallback, and enhanced docstring in `_get_model_reasoning_content_support`.
2. **Test coverage**: `tests/test_proxy_reload.py` gains:
   - `test_scoring_precedence_wildcard_provider_beats_specific_prefix`: verifies provider-matching rule with `prefix="*"` and explicit provider wins over a longer prefix without provider.
   - `test_sanitizer_deep_copies_messages`: verifies mutation of sanitized messages does not affect original body.
   - `test_unknown_provider_logs_warning`: verifies `caplog` contains warning when provider not in config and no model rule matches.
3. **Test helper fix**: `_config_text` in `tests/test_proxy_reload.py` normalizes trailing newlines on `provider_body` and `model_rules_extra`.
4. **CI passes**: `uv run pytest tests/ -q`, `uv run ruff check src/`, `uv run ruff format --check src/ tests/`, `uv run pyright src/`.

## Out of Scope

- Changing the scoring algorithm itself (the current precedence is preserved as a deliberate design choice matching `_get_model_reasoning_style`).
- Adding new config fields to `ProviderConfig` or `ModelRuleEntry`.
- Changing the OpenAI-compatible API surface or headers.
