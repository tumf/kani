---
change_type: implementation
priority: high
dependencies: []
references:
  - src/kani/config.py
  - src/kani/proxy.py
  - src/kani/router.py
  - tests/test_proxy_reload.py
  - tests/test_cli.py
  - openspec/specs/config/spec.md
  - openspec/specs/proxy-api/spec.md
---

# Add provider reasoning_style based reasoning control injection

**Change Type**: implementation

## Premise / Context

- kani is an OpenAI-compatible FastAPI proxy that routes `kani/<profile>` requests through `src/kani/proxy.py` and `src/kani/router.py`.
- Current routed requests replace only `body["model"]` before proxying upstream; provider-specific reasoning controls are not injected.
- The user wants provider-level `reasoning_style` with values like `openai`, defaulting to `openai`, and preserving client-provided reasoning controls.
- Provider APIs differ: OpenAI/OpenRouter/xAI commonly use `reasoning.effort`; Anthropic uses `output_config.effort`; DashScope/Qwen uses `enable_thinking`; Gemini native uses `generationConfig.thinkingConfig.thinkingBudget`; DeepSeek R1 should generally use `none` because official API exposes reasoning via model choice rather than effort.
- Repository conventions require config model updates in `src/kani/config.py`, proxy behavior tests, and OpenSpec deltas under `openspec/changes/<id>/`.

## Problem / Context

Kani can route a prompt to a reasoning tier, but it cannot currently add upstream-provider-specific reasoning control fields to the request payload. Operators must rely on default model/provider behavior or require clients to know each upstream provider's parameter shape. This weakens kani's role as a smart proxy and makes model/provider swaps leak into client configuration.

At the same time, reasoning controls are not standardized across providers. A single unconditional field would break providers that expect a different shape, and kani must not override explicit client settings.

## Proposed Solution

Add `reasoning_style` to provider configuration with default value `openai`. Routed `kani/<profile>` requests will consult the resolved provider's `reasoning_style` and inject the appropriate reasoning control only when the client request does not already contain any supported reasoning/thinking control.

Supported initial styles:

- `openai`: inject `reasoning: {"effort": "<effort>"}`.
- `anthropic`: inject or merge `output_config: {"effort": "<effort>"}` without overwriting an existing `output_config.effort`.
- `dashscope`: inject `enable_thinking: true|false`.
- `gemini`: inject or merge `generationConfig.thinkingConfig.thinkingBudget`.
- `none`: do not inject anything.

The implementation should derive a default control from the routing decision tier unless a more specific config knob is added in the same change. Minimal default behavior should enable stronger reasoning only for `REASONING` tier, avoid changing pass-through requests, and preserve explicit client controls.

## Acceptance Criteria

- `ProviderConfig` accepts optional `reasoning_style` with allowed values `openai`, `anthropic`, `dashscope`, `gemini`, and `none`.
- Missing `reasoning_style` remains backward-compatible and behaves as `openai`.
- Routed requests add provider-style-specific reasoning control only when no client-provided reasoning/thinking control is present.
- Routed requests do not overwrite client-provided `reasoning`, `reasoning_effort`, `thinking`, `output_config.effort`, `enable_thinking`, or `generationConfig.thinkingConfig.thinkingBudget`.
- Pass-through requests whose model does not start with `kani/` are not modified by this feature.
- Fallback attempts use the fallback provider's `reasoning_style`, not stale primary-provider style, when body shape must differ.
- Tests cover config validation/defaults, OpenAI-style injection, Anthropic-style injection, DashScope-style injection, Gemini-style injection, `none`, client override preservation, pass-through no-op, and fallback provider restyling.

## Explicit Completion Conditions

- `src/kani/config.py` exposes and validates `ProviderConfig.reasoning_style` with default `openai`.
- `src/kani/proxy.py` has a small helper that applies provider-specific reasoning controls before each upstream request and is used for primary and fallback requests.
- Unit/integration tests in `tests/` fail if reasoning controls are omitted, overwritten, injected into pass-through requests, or incorrectly reused across fallback provider changes.
- Documentation or sample config mentions `reasoning_style` and the supported values.
- `uv run ruff check src/`, `uv run ruff format --check src/ tests/`, `uv run pyright src/`, and relevant pytest coverage pass.

## Out of Scope

- Adding a full per-model reasoning-effort matrix or live provider capability discovery.
- Transforming Chat Completions payloads into native non-chat provider APIs.
- Exposing hidden chain-of-thought content to clients beyond whatever upstream already returns.
- Changing routing tier classification thresholds.
- Changing DeepSeek reasoning model selection semantics.
