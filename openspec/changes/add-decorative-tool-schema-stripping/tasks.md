## Implementation Tasks

- [ ] Add a typed decorative tool schema handling config field with default `preserve` and accepted values `preserve | strip` (verification: unit - `tests/test_cli.py` or `tests/test_config.py` proves omitted config resolves to `preserve`, `strip` is accepted, and invalid values are rejected)
- [ ] Implement a small payload adaptation helper in `src/kani/proxy.py` that accepts the upstream body plus `ToolsCapabilityDecision` and returns an adapted copy plus audit metadata (verification: unit - `tests/test_capability_routing.py` or a new proxy helper test asserts the original dict remains unchanged and stripped copies remove only top-level tool fields)
- [ ] Preserve upstream payloads by default for routed requests (verification: integration - `tests/test_api_keys_proxy.py` or `tests/test_proxy_reload.py` captures `_proxy_upstream` body and asserts `tools`, `functions`, `tool_choice`, and `function_call` remain present when config is default/preserve)
- [ ] Strip top-level `tools`, `functions`, `tool_choice`, and `function_call` only when handling policy is `strip` and the tools capability decision is `declared=True, required=False` (verification: integration - `tests/test_proxy_reload.py` routed `/v1/chat/completions` test with `tools_capability_detection: active` and stripping enabled captures upstream body without those top-level fields)
- [ ] Never strip when tool use is forced through `tool_choice` or legacy `function_call` (verification: unit/integration - `tests/test_capability_routing.py` or `tests/test_proxy_reload.py` covers forced fields and asserts upstream body preserves tool-related fields and `tools` remains required)
- [ ] Never strip when message history contains active tool state after the latest user turn (verification: unit/integration - `tests/test_proxy_reload.py` sends assistant `tool_calls` or `role="tool"` after latest user and asserts upstream body preserves tool-related fields)
- [ ] Preserve passthrough mode exactly even when stripping is configured (verification: integration - `tests/test_api_keys_proxy.py` or `tests/test_proxy_reload.py` posts a non-`kani/` model request and captures `_proxy_upstream` body with tool-related fields still present)
- [ ] Ensure fallback attempts reuse the same adapted upstream payload for the request (verification: integration - `tests/test_api_keys_proxy.py::TestProxyFallbackBehavior` or equivalent fake fallback test asserts every attempted upstream body has the same stripped/preserved tool field set)
- [ ] Add audit metadata for stripping decisions without logging schema contents (verification: integration/manual - `tests/test_proxy_reload.py` or `tests/test_router_logging.py` asserts diagnostics/log text includes policy/applied state but does not include a sentinel tool name such as `sensitive_internal_tool`)
- [ ] Update `README.md` and `config.example.yaml` to document `decorative_tool_schema_handling`, the default `preserve`, the opt-in `strip`, and the safety requirement that stripping only works with non-required decorative schemas (verification: integration - `uv run python -c "from pathlib import Path; assert 'decorative_tool_schema_handling' in Path('README.md').read_text(); assert 'decorative_tool_schema_handling' in Path('config.example.yaml').read_text()"`)
- [ ] Run quality gates after implementation (verification: integration - `uv run ruff check src/`, `uv run ruff format --check src/ tests/`, `uv run pyright src/`, `uv run pytest tests/test_capability_routing.py tests/test_proxy_reload.py tests/test_api_keys_proxy.py -q`, and broader relevant pytest pass)

## Future Work

- Provider-specific schema rewriting or translation can be proposed separately if removing top-level fields is insufficient for particular providers.
- Automatic client detection remains out of scope; operators must opt in explicitly.

## Final Validation

Archive validation itself is the authoritative final OpenSpec validation gate.
Expected archive gate: `cflx openspec validate add-decorative-tool-schema-stripping --archive-gate`
