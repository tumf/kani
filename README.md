# 🦀 kani

<p align="center">
  <img src="assets/cover.png" alt="kani — LLM smart router" width="800" />
</p>

[![CI](https://github.com/tumf/kani/actions/workflows/ci.yml/badge.svg)](https://github.com/tumf/kani/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

kani is an OpenAI-compatible local proxy that automatically routes LLM requests to the most suitable model.
It classifies each request by prompt complexity, required capabilities, and your cost/quality profile.

Use kani when you want to:

- use one OpenAI-compatible endpoint across OpenAI, OpenRouter, local proxies, and other providers
- reduce cost by routing simple prompts to cheaper models
- keep stronger models for complex, agentic, or reasoning-heavy work
- inspect routing decisions through headers, logs, and debug endpoints

## Quick start

### Requirements

- Python 3.13+
- uv
- At least one OpenAI-compatible provider API key, for example `OPENROUTER_API_KEY`

### Try the router only

This classifies a prompt without running the proxy server.

```bash
uvx --from git+https://github.com/tumf/kani kani route "hello world"
```

### Run as a proxy server

```bash
git clone https://github.com/tumf/kani.git
cd kani
uv sync
cp config.example.yaml config.yaml
cp .env.example .env
```

Edit `.env`:

```bash
OPENROUTER_API_KEY=your-openrouter-api-key
```

Start kani:

```bash
uv run kani serve
```

By default, kani listens on `http://localhost:18420/v1`.

Send an OpenAI-compatible request:

```bash
curl http://localhost:18420/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "kani/auto",
    "messages": [
      {"role": "user", "content": "explain quicksort"}
    ]
  }'
```

Debug routing without proxying upstream:

```bash
uv run kani route "explain quicksort"
```

## Usage — drop-in replacement for OpenAI / OpenRouter

kani speaks the OpenAI API. Change `base_url` and `model`; keep the rest of your client code the same.

### Before: direct OpenAI

```python
from openai import OpenAI

client = OpenAI(api_key="sk-...")

response = client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "explain quicksort"}],
)
```

### Before: OpenRouter

```python
from openai import OpenAI

client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key="sk-or-...",
)

response = client.chat.completions.create(
    model="anthropic/claude-sonnet-4",
    messages=[{"role": "user", "content": "explain quicksort"}],
)
```

### After: kani auto-routes

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:18420/v1",
    api_key="kani-local-dev",  # ignored unless kani API key auth is enabled
)

response = client.chat.completions.create(
    model="kani/auto",
    messages=[{"role": "user", "content": "explain quicksort"}],
)

response = client.chat.completions.create(
    model="kani/premium",
    messages=[{"role": "user", "content": "prove P != NP"}],
)
```

Any tool or library that supports the OpenAI API works with kani: LangChain, LlamaIndex, Cursor, Continue, and similar clients.

## API keys

kani uses two different kinds of keys:

1. **Upstream provider keys**
   - Used by kani to call OpenAI, OpenRouter, local proxies, and other providers.
   - Configured in `config.yaml` or environment variables such as `OPENROUTER_API_KEY`.
2. **kani proxy API keys**
   - Used by clients to authenticate to kani itself.
   - Optional. If no kani keys are configured, requests are accepted without authentication.

Enable kani proxy authentication:

```bash
uv run kani keys add my-client
```

Use the generated key as the OpenAI client API key:

```python
client = OpenAI(
    base_url="http://localhost:18420/v1",
    api_key="kani-aBcDeFgH...",
)
```

When at least one kani proxy key exists, every API request must include `Authorization: Bearer <key>`. `/health` and `/docs` are exempt.

## Routing profiles

Profiles are examples. Tune names, strategies, and model mappings for your workload and cost/quality goals.

| Profile | Strategy | Best for |
|---------|----------|----------|
| `kani/auto` | Balanced cost/quality | General use |
| `kani/eco` | Cheapest viable models | High volume, low stakes |
| `kani/premium` | Best quality models | Critical tasks |
| `kani/agentic` | Tool-use optimized | Agent workflows |

## Minimal configuration

`config.yaml`:

```yaml
host: "0.0.0.0"
port: 18420

default_provider: openrouter
default_profile: auto

providers:
  openrouter:
    name: openrouter
    base_url: "https://openrouter.ai/api/v1"
    api_key: "${OPENROUTER_API_KEY}"

profiles:
  auto:
    tiers:
      SIMPLE:
        primary: "gpt-4o-mini"
      MEDIUM:
        primary: "gpt-4o-mini"
      COMPLEX:
        primary: "gpt-4o"
      REASONING:
        primary: "gpt-4o"
```

For a full example with embeddings, model metadata, fallback backoff, tool detection, and context compaction, see `config.example.yaml`.

Config path resolution order:

1. `--config` flag
2. `$KANI_CONFIG`
3. `./config.yaml`
4. `$XDG_CONFIG_HOME/kani/config.yaml`
5. `/etc/kani/config.yaml`

### Important: model IDs are provider-specific

kani does not rewrite model IDs. Configured model IDs are sent literally to the selected provider.

For OpenRouter, use OpenRouter model IDs:

```yaml
primary: "anthropic/claude-sonnet-4"
```

For OpenAI, use OpenAI model IDs:

```yaml
primary: "gpt-4o"
```

To route the same profile to different providers, set `provider` on the model entry or tier.

## Capability-aware routing

kani detects required capabilities from the request and routes to a model that supports them. If no model in the scored tier has the required capabilities, kani escalates to higher tiers.

| Capability | Trigger |
|------------|---------|
| `vision` | `image_url` content block in messages |
| `tools` | `tools` or `functions` field by default; configurable |
| `json_mode` | `response_format.type` is `json_object` or `json_schema` |

Declare model metadata with prefix matching:

```yaml
model_rules:
  - prefix: "anthropic/claude-"
    capabilities: [vision, tools, json_mode]
  - prefix: "google/gemini-"
    capabilities: [vision, tools, json_mode]
  - prefix: "gpt-4"
    capabilities: [vision, tools, json_mode]
```

`model_rules` is the primary metadata key. The legacy `model_capabilities` key is accepted only when `model_rules` is unset.

## API endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/v1/chat/completions` | POST | Main proxy, OpenAI-compatible |
| `/v1/models` | GET | List available models |
| `/v1/route` | POST | Return routing decision without proxying upstream |
| `/admin/reload-config` | POST | Admin-only safe config hot reload |
| `/health` | GET | Health and active config version metadata |

## Debug routing

Use `/v1/route` to see which tier and model kani would choose without sending the request upstream.

```bash
curl http://localhost:18420/v1/route \
  -H "Content-Type: application/json" \
  -d '{
    "model": "kani/auto",
    "messages": [
      {"role": "user", "content": "write a detailed migration plan"}
    ]
  }'
```

For proxied requests, inspect response headers:

```bash
curl -i http://localhost:18420/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"kani/auto","messages":[{"role":"user","content":"hello"}]}'
```

Look for:

- `X-Kani-Tier`
- `X-Kani-Model`
- `X-Kani-Score`
- `X-Kani-Signals`

## How it works

```text
Request → Distilled Feature Classifier → Tier + Agentic Score → Capability Filter → Model Selection → Upstream Provider
                                                   │
                                                   └─ model unavailable → conservative default
```

Classification pipeline:

1. Deterministic `tokenCount` plus learned semantic dimensions.
2. Separate complexity and reasoning scores drive tier selection.
3. `agenticTask` is exposed as `agentic_score` without affecting tier.
4. Missing feature model, embedding config, embedding request, or prediction path falls back to `MEDIUM`.
5. Capability filtering detects vision, tools, and JSON mode requirements.

Runtime routing does not call an LLM. LLM usage is limited to optional offline dataset annotation.

## Scoring approach

kani is distilled-feature-first:

- compute `tokenCount` deterministically
- infer 14 semantic dimensions with a learned multi-output classifier
- compute separate complexity and reasoning axis scores
- determine `SIMPLE`, `MEDIUM`, `COMPLEX`, or `REASONING`
- expose `agentic_score` independently
- return conservative default routing when feature scoring is unavailable

Tier thresholds:

- `REASONING`: `reasoning_score >= 0.75`
- `COMPLEX`: `complexity_score >= 0.8`
- `MEDIUM`: `complexity_score >= 0.5`
- `SIMPLE`: below all thresholds

Routing improves through retraining and calibration rather than runtime prompt engineering.

## Advanced features

### Smart-proxy context compaction

Context compaction is opt-in and disabled by default. It can compact oversized message histories inline before proxying upstream and pre-compute summaries in the background for later reuse.

Minimal shape:

```yaml
smart_proxy:
  context_compaction:
    enabled: true
    sync_compaction:
      enabled: true
      threshold_percent: 80.0
    background_precompaction:
      enabled: true
      trigger_percent: 70.0
    session:
      header_name: X-Kani-Session-Id
    context_window_tokens: 128000
```

Compaction headers:

| Header | Values | Meaning |
|--------|--------|---------|
| `X-Kani-Compaction` | `off` \| `skipped` \| `inline` \| `cached` \| `failed` | What compaction did |
| `X-Kani-Compaction-Session` | `explicit` \| `none` | How session was resolved |
| `X-Kani-Compaction-Saved-Tokens` | integer | Estimated tokens saved |

Compaction state is persisted in SQLite under `$XDG_DATA_HOME/kani/compaction.db` by default. Override with `KANI_DATA_DIR`.

### Safe config hot reload

Set `KANI_ADMIN_TOKEN` to enable admin-only config reload:

```bash
export KANI_ADMIN_TOKEN="your-admin-token"
curl -X POST http://localhost:18420/admin/reload-config \
  -H "Authorization: Bearer ${KANI_ADMIN_TOKEN}"
```

Reload validates with strict config validation. Changes to `host` or `port` are rejected with `409` and require restart.

### Routing logs and classifier training

All routing decisions are logged to `$XDG_STATE_HOME/kani/log/routing-YYYY-MM-DD.jsonl`, defaulting to `~/.local/state/kani/log/`.

Use logs to build training data:

```bash
uv run python scripts/build_agentic_dataset.py \
  --output data/distilled_feature_dataset.json
```

Annotate missing semantic labels offline:

```bash
uv run python scripts/build_agentic_dataset.py \
  --annotate-missing \
  --output data/distilled_feature_dataset.json
```

Train the feature classifier bundle:

```bash
uv run python scripts/train_classifier.py \
  --data data/distilled_feature_dataset.json \
  --output models
```

This writes `models/feature_classifier.pkl` with the classifier, label encoders, weights, thresholds, and embedding metadata.

### Offline feature annotation

Optional annotator configuration:

```yaml
feature_annotator:
  model: "gemini-2.5-flash-lite"
  provider: "openrouter"
```

Priority is CLI flags, environment variables, `config.yaml` `feature_annotator`, then built-in defaults.

## CLI

```bash
kani serve [--config path] [--host 0.0.0.0] [--port 18420]
kani route "your prompt here" [--config path]
kani config [--config path]
kani keys add <name>
kani keys list
kani keys remove <name|prefix>
```

## Architecture

```text
src/kani/
├── scorer.py    # distilled feature scoring
├── router.py    # tier to model/provider mapping
├── proxy.py     # FastAPI OpenAI-compatible server
├── config.py    # YAML config loading and env var resolution
├── dirs.py      # XDG-compliant directory paths
├── logger.py    # JSONL routing log
└── cli.py       # Click CLI
```

## Development

```bash
uv sync --dev
uv run ruff check src/
uv run ruff format --check src/ tests/
uv run pyright src/
uv run pytest tests/ -q
uv build
```

## Credits

Scoring logic ported from [ClawRouter](https://github.com/BlockRunAI/ClawRouter) under the MIT license.

## License

MIT
