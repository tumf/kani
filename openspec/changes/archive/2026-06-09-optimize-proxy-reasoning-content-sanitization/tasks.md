## Implementation Tasks

- [x] Optimize `sanitize_reasoning_content` in `src/kani/proxy.py` to scan before copying. (verification: unit - `uv run pytest tests/test_proxy_reload.py -q -k reasoning_content`; completion: when no message contains `reasoning_content`, the original body object is returned and no message deep copy is performed.)
- [x] Preserve mutation isolation for messages that do contain `reasoning_content`. (verification: unit - `uv run pytest tests/test_proxy_reload.py -q -k reasoning_content`; completion: only affected dict messages are shallow-copied and sanitized; original request message dictionaries still retain `reasoning_content`.)
- [x] Replace private docstring wording assertions with behavior assertions for provider-rule precedence. (verification: unit - `uv run pytest tests/test_proxy_reload.py -q -k provider_specific_wildcard`; completion: tests cover provider-specific wildcard precedence through `_get_model_reasoning_content_support` outcomes rather than helper docstring text.)
- [x] Run formatting, lint, typecheck, and targeted proxy tests. (verification: integration - `uv run ruff check src/ && uv run ruff format --check src/ tests/ && uv run pyright src/ && uv run pytest tests/test_proxy_reload.py -q`; completion: all commands exit successfully.)

## Future Work

- None.

## Final Validation

Expected archive gate: `cflx openspec validate optimize-proxy-reasoning-content-sanitization --archive-gate`
