## Implementation Tasks

- [x] Document reasoning-content model-rule precedence in `src/kani/proxy.py`. Completion condition: `_get_model_reasoning_content_support` docstring states that provider-matching rules outrank provider-agnostic rules before prefix specificity is considered. verification: unit - `uv run pytest tests/test_proxy_reload.py -q -k scoring_precedence`

- [x] Add unit coverage for wildcard provider-specific precedence in `tests/test_proxy_reload.py`. Completion condition: a test constructs conflicting model rules where `{prefix: "*", provider: "dummy", supports_reasoning_content: False}` beats `{prefix: "sonnet-", supports_reasoning_content: True}` for provider `dummy`. verification: unit - `uv run pytest tests/test_proxy_reload.py -q -k scoring_precedence`

- [x] Add warning logging for unknown provider reasoning-content fallback in `src/kani/proxy.py`. Completion condition: `_supports_reasoning_content` logs a warning when no model rule matches and `provider_name` is missing from `runtime.config.providers`, while still returning `False`. verification: unit - `uv run pytest tests/test_proxy_reload.py -q -k unknown_provider`

- [x] Deep-copy sanitized message dicts in `src/kani/proxy.py`. Completion condition: `_sanitize_reasoning_content_for_candidate` returns a body whose `messages` entries are independent copies whenever sanitization occurs. verification: unit - `uv run pytest tests/test_proxy_reload.py -q -k sanitizer_deep_copies_messages`

- [x] Normalize optional YAML fragments in `tests/test_proxy_reload.py::_config_text`. Completion condition: `provider_body` and `model_rules` fragments are accepted with or without trailing newline and produce parseable YAML. verification: unit - `uv run pytest tests/test_proxy_reload.py -q -k config_text`

- [x] Run focused regression tests for reasoning-content compatibility. Completion condition: reasoning-content primary, fallback, supported-model, passthrough, and routing-tier tests pass. verification: unit - `uv run pytest tests/test_proxy_reload.py -q -k reasoning_content`

- [x] Run project quality gates. Completion condition: lint, format check, typecheck, and full tests pass locally. verification: integration - `uv run ruff check src/ && uv run ruff format --check src/ tests/ && uv run pyright src/ && uv run pytest tests/ -q`

## Future Work

None.

## Final Validation

Archive validation itself is the authoritative final OpenSpec validation gate.
Expected archive gate: `cflx openspec validate harden-reasoning-content-compat --archive-gate`
