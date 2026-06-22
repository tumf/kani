## Implementation Tasks

- [x] Add a typed configuration field for tools capability detection policy with a backward-compatible default of `declared` (verification: unit - `tests/test_config.py` or `tests/test_cli.py` proves omitted config resolves to `declared` and invalid values are rejected)
- [x] Refactor `src/kani/proxy.py` capability detection so tool declarations and tool-required decisions are separate helper responsibilities (verification: unit - `tests/test_capability_routing.py::TestCapabilityDetection` covers helper outputs without invoking upstream providers)
- [x] Preserve declared-policy behavior where any `tools` or `functions` request field requires the `tools` capability (verification: unit - `tests/test_capability_routing.py::TestCapabilityDetection::test_detect_tools_capability_via_tools_field` and `tests/test_capability_routing.py::TestCapabilityDetection::test_detect_tools_capability_via_functions_field` remain equivalent under default config)
- [x] Implement active-policy behavior so decorative `tools`/`functions` declarations do not require `tools` when there is no explicit or active tool use (verification: unit - add `tests/test_capability_routing.py::TestCapabilityDetection::test_active_policy_ignores_decorative_tools_field` asserting `tools` is absent for schema-only requests)
- [x] Treat explicit forced tool use as requiring `tools` under active policy, including `tool_choice="required"`, specific function/tool choices, and legacy `function_call` forcing (verification: unit - add `tests/test_capability_routing.py::TestCapabilityDetection::test_active_policy_detects_forced_tool_choice` and legacy function-call variants)
- [x] Treat active tool history after the latest user message as requiring `tools`, including assistant `tool_calls`, legacy assistant `function_call`, `role="tool"`, and legacy `role="function"` messages (verification: unit - add `tests/test_capability_routing.py::TestCapabilityDetection::test_active_policy_detects_active_tool_history` variants)
- [x] Treat resolved historical tool activity before the latest user message as no longer active under active policy (verification: unit - add `tests/test_capability_routing.py::TestCapabilityDetection::test_active_policy_ignores_tool_history_before_latest_user`)
- [x] Preserve capability fail-closed routing for all tool-required requests after policy evaluation (verification: integration - `tests/test_capability_routing.py::TestCapabilityFiltering` includes a request that evaluates to `tools` required and fails with `CapabilityNotSatisfiedError` when candidates lack `tools`)
- [x] Make the tools capability policy decision auditable through routing diagnostics or logs without leaking tool schema contents (verification: integration/manual - targeted logging assertion in `tests/test_router_logging.py` or manual `uv run kani route`/proxy request confirms policy/method is present while tool schema names are absent)
- [x] Update `README.md` and committed config example documentation for default `declared` behavior, opt-in `active` behavior, OpenCode-style decorative schema use case, and safety trade-offs (verification: integration - `uv run python -c "from pathlib import Path; assert 'tools_capability_detection' in Path('README.md').read_text(); assert 'tools_capability_detection' in Path('config.example.yaml').read_text()"`)
- [x] Run quality gates after implementation (verification: integration - `uv run ruff check src/`, `uv run ruff format --check src/ tests/`, `uv run pyright src/`, `uv run pytest tests/test_capability_routing.py -q`, and broader relevant pytest pass)

## Future Work

- Consider provider-specific tool capability metadata discovery only if reliable upstream metadata becomes available.
- Consider tool schema pruning or tool discovery optimization as a separate smart-proxy feature; it should not be coupled to this routing policy.

## Final Validation

Archive validation itself is the authoritative final OpenSpec validation gate.
Expected archive gate: `cflx openspec validate refine-tools-capability-detection --archive-gate`
