# Contributing to kani

This document is for developers changing kani internals.
For user-facing setup and usage, see `README.md`.
For dashboard and production deployment notes, see `README.DASHBOARD.md`.
For coding-agent-specific instructions, see `AGENTS.md`.

## Project snapshot

kani is a Python 3.13+ project.

Core shape:

- Package manager and task runner: `uv`
- CLI: Click
- Proxy server: FastAPI
- Config models: Pydantic
- HTTP client: httpx
- Source tree: `src/kani/`
- Tests: `tests/`
- Type checking: pyright
- Lint and format: ruff
- Build backend: `uv_build`

CLI entrypoint:

```toml
kani = "kani.cli:main"
```

## Branch and PR policy

CI runs on pushes and pull requests targeting `main`.
Open PRs against `main` unless repository policy changes.
If a `develop` branch becomes the integration branch, update this section together with `.github/workflows/ci.yml`.

## Local development setup

Clone and install development dependencies:

```bash
git clone https://github.com/tumf/kani.git
cd kani
uv sync --dev
```

Create a local config:

```bash
cp config.example.yaml config.yaml
```

Set at least one provider key in your shell environment:

```bash
export OPENROUTER_API_KEY="..."
```

Local `uv run kani ...` does not automatically load `.env`.
Use your shell, direnv, dotenvx, or another dotenv loader if you prefer keeping secrets in a file.

Check the local configuration:

```bash
uv run kani doctor --config config.yaml
uv run kani config --config config.yaml
```

Classify a prompt without starting the proxy:

```bash
uv run kani route "hello world" --config config.yaml
```

Start the proxy:

```bash
uv run kani serve --config config.yaml
```

Default local endpoint:

```text
http://localhost:18420/v1
```

## Common development commands

Install dependencies:

```bash
uv sync --dev
```

Run all default tests:

```bash
uv run pytest tests/ -q
```

Run one test file:

```bash
uv run pytest tests/test_scorer.py -q
```

Run tests matching a keyword:

```bash
uv run pytest tests/ -q -k routing
```

Run lint:

```bash
uv run ruff check src/
```

Run format check:

```bash
uv run ruff format --check src/ tests/
```

Apply formatting:

```bash
uv run ruff format src/ tests/
```

Run type checking:

```bash
uv run pyright src/
```

Build package artifacts:

```bash
uv build
```

Recommended pre-PR check:

```bash
uv run ruff check src/
uv run ruff format --check src/ tests/
uv run pyright src/
uv run pytest tests/ -q
uv build
```

## CI expectations

The CI acceptance bar is:

```bash
uv sync --dev
uv run ruff check src/
uv run ruff format --check src/ tests/
uv run pyright src/
uv run pytest tests/ -q
uv build
```

Run the relevant subset while developing, then run the full pre-PR check before opening a PR.
If branch policy changes, update this section together with `.github/workflows/ci.yml`.

## Repository layout

Core runtime modules:

```text
src/kani/
├── cli.py                    # Click commands: serve, route, doctor, config, init, keys
├── config.py                 # YAML config loading, env-var resolution, validation
├── router.py                 # Tier/profile/provider/model selection
├── scorer.py                 # Distilled feature classification and tier scoring
├── classification_context.py # Request-to-classification context helpers
├── proxy.py                  # FastAPI OpenAI-compatible proxy server
├── fallback_backoff.py       # Process-local fallback cooldowns
├── api_keys.py               # kani proxy API key storage and validation
├── logger.py                 # JSONL routing log writer
├── dirs.py                   # XDG/platformdirs helpers
├── compaction.py             # Smart-proxy context compaction logic
├── compaction_store.py       # SQLite-backed compaction state
├── dashboard.py              # Dashboard ingestion, stats, and HTML rendering
├── training_data.py          # Distilled feature dataset data structures/helpers
├── feature_training.py       # Multi-output feature classifier training
└── agentic_training.py       # Agentic training helpers
```

Scripts:

```text
scripts/
├── build_agentic_dataset.py      # Build distilled feature dataset from logs
├── train_classifier.py           # Train the current feature classifier bundle
├── bootstrap_agentic_dataset.py  # Bootstrap agentic examples
├── train_agentic_classifier.py   # Legacy/experimental agentic classifier path
├── annotate_reasoning.py         # Offline annotation helper
├── annotate_synthetic.py         # Offline synthetic annotation helper
└── test_scorer.py                # Manual scorer script
```

Tests live under `tests/`.

## Runtime request flow

High-level proxy flow:

```text
OpenAI-compatible client
  -> FastAPI proxy
  -> API key middleware, if kani keys exist
  -> capability detection: vision / tools / json_mode
  -> Router.route(...)
  -> Scorer classification
  -> tier/profile/provider/model selection
  -> input-limit and capability filtering
  -> upstream OpenAI-compatible provider
  -> response headers + routing logs + dashboard ingestion
```

Classifier flow:

```text
messages
  -> tokenCount
  -> semantic feature prediction
  -> complexity score
  -> reasoning score
  -> SIMPLE / MEDIUM / COMPLEX / REASONING
  -> independent agentic_score
```

Runtime routing should stay safe under failures:

- Do not call an LLM at runtime just to classify prompts.
- If the feature classifier, embedding config, embedding request, or prediction path fails, fall back conservatively.
- Keep fallback behavior explicit and test-covered.
- Prefer fail-closed behavior for required capabilities.

## Configuration and secrets

Config files should use environment placeholders for secrets:

```yaml
providers:
  openrouter:
    name: openrouter
    base_url: "https://openrouter.ai/api/v1"
    api_key: "${OPENROUTER_API_KEY}"
```

Do not hardcode real API keys in:

- source code
- tests
- docs
- examples
- committed config files

When changing config semantics, update all relevant places:

- `src/kani/config.py`
- `config.example.yaml`
- `README.md`
- `CONTRIBUTING.md`, if developer-facing behavior changes
- tests under `tests/test_config.py` and related integration tests

Important config behavior to preserve:

- Config path precedence should remain documented and tested.
- `${VAR}` placeholders should continue resolving from environment variables.
- `kani doctor` must not print secrets.
- Model IDs are provider-specific and should be sent to the selected provider without hidden rewriting.
- Provider resolution should remain explicit and predictable.

## API key authentication

kani has two kinds of API keys:

1. Upstream provider API keys
   - Used by kani to call providers such as OpenRouter or OpenAI.
   - Configured through `config.yaml` and environment variables.
2. kani proxy API keys
   - Used by clients to authenticate to kani itself.
   - Managed through `kani keys`.
   - Optional. If no kani keys exist, proxy auth is disabled for backward compatibility.

Useful commands:

```bash
uv run kani keys add local-dev
uv run kani keys list
uv run kani keys remove local-dev
```

When touching auth behavior, run:

```bash
uv run pytest tests/test_api_keys.py -q
uv run pytest tests/test_api_keys_cli.py -q
uv run pytest tests/test_api_keys_proxy.py -q
```

## Routing and capability changes

When changing routing behavior, check whether the change affects:

- tier scoring
- profile selection
- provider resolution
- model candidate ordering
- round-robin selection
- fallback behavior
- input token limits
- capability filtering
- response headers
- routing logs
- dashboard ingestion

Relevant tests:

```bash
uv run pytest tests/test_scorer.py -q
uv run pytest tests/test_capability_routing.py -q
uv run pytest tests/test_input_limit_routing.py -q
uv run pytest tests/test_fallback_backoff.py -q
uv run pytest tests/test_router_logging.py -q
```

Add tests for:

- success path
- fallback path
- no-capable-model path
- too-small-input-window path
- malformed or incomplete config
- conservative default behavior

## Proxy changes

When changing `src/kani/proxy.py`, check whether the change affects:

- OpenAI-compatible request/response shape
- streaming behavior
- non-streaming behavior
- response headers
- error shape
- API key middleware
- config hot reload
- compaction behavior
- dashboard ingestion
- fallback execution

Relevant tests:

```bash
uv run pytest tests/test_proxy_reload.py -q
uv run pytest tests/test_api_keys_proxy.py -q
uv run pytest tests/test_compaction.py -q
uv run pytest tests/test_dashboard.py -q
```

Proxy errors should remain OpenAI-style JSON errors rather than raw exception responses.

## Config hot reload

`POST /admin/reload-config` is admin-only and uses `KANI_ADMIN_TOKEN`.

Behavior to preserve:

- Reload validates config before applying.
- In-flight requests keep their existing runtime state snapshot.
- Non-reloadable fields such as host and port require process restart.
- Admin auth is separate from regular kani proxy API keys.

When changing reload behavior, run:

```bash
uv run pytest tests/test_proxy_reload.py -q
uv run pytest tests/test_config.py -q
```

## Smart-proxy context compaction

Context compaction is opt-in and disabled by default.

Main modules:

- `src/kani/compaction.py`
- `src/kani/compaction_store.py`
- `src/kani/proxy.py`

Compaction failures should not break the proxied user request.
If compaction fails, the proxy should route and proxy the original request.

When changing compaction behavior, run:

```bash
uv run pytest tests/test_compaction.py -q
```

Also check:

```bash
curl -s http://localhost:18420/health | jq .
```

And inspect response headers on a routed request:

```bash
curl -i http://localhost:18420/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "X-Kani-Session-Id: dev-session" \
  -d '{"model":"kani/auto","messages":[{"role":"user","content":"hello"}]}'
```

Relevant headers:

```text
X-Kani-Compaction
X-Kani-Compaction-Session
X-Kani-Compaction-Saved-Tokens
```

## Routing logs

Routing decisions are written to JSONL logs.

Default location:

```text
$XDG_STATE_HOME/kani/log/routing-YYYY-MM-DD.jsonl
```

Common local default:

```text
~/.local/state/kani/log/routing-YYYY-MM-DD.jsonl
```

Inspect logs:

```bash
tail -f ~/.local/state/kani/log/routing-$(date +%F).jsonl
```

Routing logs are used as input for offline dataset generation, so keep log schema changes deliberate and documented.

If changing log fields, update:

- `src/kani/logger.py`
- dashboard ingestion
- dataset-building scripts
- relevant tests
- docs that mention response headers or log fields

Relevant tests:

```bash
uv run pytest tests/test_router_logging.py -q
uv run pytest tests/test_dashboard.py -q
```

## Response headers

Routed responses include debugging headers:

```text
X-Kani-Tier
X-Kani-Model
X-Kani-Score
X-Kani-Signals
```

Compaction may add:

```text
X-Kani-Compaction
X-Kani-Compaction-Session
X-Kani-Compaction-Saved-Tokens
```

If adding, renaming, or removing headers, update:

- `README.md`
- `CONTRIBUTING.md`
- proxy tests
- dashboard/docs if relevant

## Feature dataset generation

Build training data from routing logs:

```bash
uv run python scripts/build_agentic_dataset.py \
  --output data/distilled_feature_dataset.json
```

If logs are missing semantic labels, use offline annotation:

```bash
uv run python scripts/build_agentic_dataset.py \
  --output data/distilled_feature_dataset.json \
  --annotate-missing
```

LLM annotation is for offline dataset generation only.
Do not add runtime LLM fallback for classification.

## Feature model training

Train the multi-output classifier bundle:

```bash
uv run python scripts/train_classifier.py \
  --data data/distilled_feature_dataset.json \
  --output models
```

Expected output:

```text
models/feature_classifier.pkl
```

The classifier bundle should include:

- multi-output classifier
- per-dimension label encoders
- embedding metadata
- default feature weights
- tier thresholds
- feature schema version

When changing classifier training, run:

```bash
uv run pytest tests/test_feature_training.py -q
uv run pytest tests/test_agentic_training_data.py -q
uv run pytest tests/test_agentic_training_script.py -q
```

Also run scorer tests:

```bash
uv run pytest tests/test_scorer.py -q
```

## Dashboard changes

Dashboard-related files:

- `src/kani/dashboard.py`
- `README.DASHBOARD.md`
- `grafana-dashboard-kani.json`
- `grafana-datasource-kani-sqlite.yml`
- `kani-dashboard-kani.json`

Relevant test:

```bash
uv run pytest tests/test_dashboard.py -q
```

Manual local check:

```bash
uv run kani serve --config config.yaml
open http://localhost:18420/dashboard
curl http://localhost:18420/dashboard/stats?hours=24
```

If dashboard metrics are zero while requests are flowing, check log paths and volume mounts first.

## Coding style

Use the existing code style.

General rules:

- Use `from __future__ import annotations` in Python modules.
- Prefer explicit imports.
- Keep imports grouped as standard library, third-party, local package.
- Use modern type syntax such as `str | None`.
- Prefer built-in generics such as `list[str]` and `dict[str, Any]`.
- Keep `Any` at boundaries such as YAML, JSON, and external request payloads.
- Use Pydantic models for config and API-facing structured data.
- Keep FastAPI handlers thin where possible.
- Keep Click commands simple and explicit.
- Avoid adding dependencies unless the benefit is clear.

Error handling:

- Raise clear errors for invalid internal config.
- Return structured OpenAI-style JSON errors at HTTP boundaries.
- Catch narrow exceptions where possible.
- For optional integrations, degrade gracefully rather than crashing the proxy.

Formatting:

- Let Ruff format the code.
- Do not hand-format against Ruff.
- Use 4-space indentation.

## Testing conventions

Tests should live under `tests/`.

Use pytest style:

```python
def test_example_behavior():
    assert actual == expected
```

Prefer:

- plain `assert`
- focused test cases
- explicit fixtures
- `unittest.mock.MagicMock` or `patch` for external/network behavior
- tests for both success and fallback paths

When adding routing or scoring logic, include edge cases:

- empty prompt
- long prompt
- reasoning-heavy prompt
- tool-use request
- vision request
- JSON-mode request
- model capability mismatch
- input window mismatch
- missing classifier
- disabled embeddings

## Change-impact checklist

When changing config:

- update `src/kani/config.py`
- update `config.example.yaml`
- update README configuration docs
- update tests

When changing routing:

- update scorer/router tests
- update response headers/log docs if affected
- update README if user-visible behavior changes

When changing proxy behavior:

- preserve OpenAI-compatible shapes
- update proxy tests
- update README API endpoint docs if needed

When changing auth:

- update API key tests
- verify auth-exempt endpoints
- ensure secrets are redacted

When changing compaction:

- update compaction tests
- update README compaction docs
- update dashboard/log ingestion if fields change

When changing training:

- update training tests
- update generated model metadata expectations
- document any schema/version changes

When changing dashboard:

- update dashboard tests
- update `README.DASHBOARD.md`
- check local dashboard manually

## Pull request checklist

Before opening a PR:

```bash
uv run ruff check src/
uv run ruff format --check src/ tests/
uv run pyright src/
uv run pytest tests/ -q
uv build
```

Also check:

- No real API keys or secrets are committed.
- Config examples still work.
- README is updated for user-visible behavior.
- CONTRIBUTING is updated for developer-facing behavior.
- Dashboard docs are updated for dashboard or analytics changes.
- Tests cover both success and fallback behavior.
- New dependencies are justified.

## Credits

Scoring logic was originally ported from ClawRouter under the MIT license.
