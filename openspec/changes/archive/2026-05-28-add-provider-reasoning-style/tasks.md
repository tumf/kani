# Tasks

## Implementation Tasks

- [x] Add `reasoning_style` to provider configuration in `src/kani/config.py` with allowed values `openai`, `anthropic`, `dashscope`, `gemini`, and `none`, defaulting to `openai`. (verification: unit - src/kani/config.py, tests/test_config.py)
- [x] Define routed-request reasoning-control injection helpers in `src/kani/proxy.py` that map routing tier and provider `reasoning_style` to provider-specific payload fields. (verification: unit - src/kani/proxy.py, tests/test_proxy_reload.py)
- [x] Preserve explicit client reasoning controls by detecting `reasoning`, `reasoning_effort`, `thinking`, `output_config.effort`, `enable_thinking`, and `generationConfig.thinkingConfig.thinkingBudget` before injecting defaults. (verification: unit - src/kani/proxy.py, tests/test_proxy_reload.py)
- [x] Wire injection into the routed primary request path after model resolution and before upstream proxying, without changing pass-through requests. (verification: integration - src/kani/proxy.py, tests/test_proxy_reload.py)
- [x] Ensure fallback attempts restyle the payload for each fallback provider instead of reusing a provider-specific payload from the primary attempt. (verification: integration - src/kani/proxy.py, tests/test_proxy_reload.py)
- [x] Update sample configuration or README configuration text to document `reasoning_style` values and default behavior. (verification: manual - tests/test_cli.py)
- [x] Run repository quality checks for changed Python behavior. (verification: integration - `uv run ruff check src/`, `uv run ruff format --check src/ tests/`, `uv run pyright src/`, and targeted pytest pass)

## Future Work

- Add per-model or per-prefix reasoning effort/budget configuration if operators need more granular tuning than tier-derived defaults.
- Add provider-specific integration smoke tests against real upstream APIs when credentials and cost budget are available.

## Final Validation

Archive validation itself is the authoritative final OpenSpec validation gate.
Expected archive gate: `cflx openspec validate add-provider-reasoning-style --archive-gate`
