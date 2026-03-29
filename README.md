# 🦀 kani

<p align="center">
  <img src="assets/cover.png" alt="kani — LLM smart router" width="800" />
</p>

[![CI](https://github.com/tumf/kani/actions/workflows/ci.yml/badge.svg)](https://github.com/tumf/kani/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

LLM smart router. Classifies prompts by complexity and routes to the optimal model.

OpenAI API-compatible proxy — drop in as a base URL and let kani pick the right model automatically.

## How it works

```
Request → Embedding Classifier → Tier → Capability Filter → Model Selection (round-robin) → Upstream Provider
                 │                              │
                 │                              └─ no capable model → escalate tier
                 └─ uncertain / unavailable → LLM Classifier → conservative default
```

**Classification pipeline:**

1. **Embedding classifier** — pre-trained sklearn model (primary path)
2. **LLM-as-judge** — cheap fallback for uncertain or unavailable embedding decisions
3. **Agentic classifier** — for the `agentic` profile, SIMPLE prompts can be re-labeled as action-oriented before routing
4. **Conservative default** — fall back to `MEDIUM` when neither classifier can decide
5. **Capability filter** — auto-detects vision/tools/json_mode from the request and escalates to a capable model

Every request is logged to `$XDG_STATE_HOME/kani/log/` (default: `~/.local/state/kani/log/`) as training data for future model improvement.

## Scoring approach

kani no longer relies on hand-maintained keyword lists inside `scorer.py`.
The scorer is now model-first:

- use the trained embedding classifier when confidence is high enough
- escalate ambiguous cases to a cheap LLM classifier
- return a conservative default tier instead of brittle keyword heuristics

This makes routing behavior easier to improve with data, because changes come from retraining or prompt tuning rather than editing keyword tables.

## Quick start

### Try without installing (uvx)

```bash
# Classify a prompt
uvx --from git+https://github.com/tumf/kani kani route "hello world"

# Start the proxy server
uvx --from git+https://github.com/tumf/kani kani serve
```

### Local install

```bash
git clone https://github.com/tumf/kani.git && cd kani
uv sync

uv run kani route "hello world"
uv run kani serve
```

## Usage — drop-in replacement for OpenAI / OpenRouter

kani speaks the OpenAI API. Change `base_url` and `model`, everything else stays the same.

### Before (direct OpenAI)

```python
from openai import OpenAI

client = OpenAI(
    api_key="sk-...",                          # OpenAI key
)

response = client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "explain quicksort"}],
)
```

### Before (OpenRouter)

```python
from openai import OpenAI

client = OpenAI(
    base_url="https://openrouter.ai/api/v1",  # OpenRouter
    api_key="sk-or-...",                       # OpenRouter key
)

response = client.chat.completions.create(
    model="anthropic/claude-sonnet-4",
    messages=[{"role": "user", "content": "explain quicksort"}],
)
```

### After (kani) — auto-routed

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:18420/v1",      # ← kani
    api_key="anything",                        # kani handles upstream auth
)

# kani picks the best model based on prompt complexity
response = client.chat.completions.create(
    model="kani/auto",
    messages=[{"role": "user", "content": "explain quicksort"}],
)

# Or pin a routing profile
response = client.chat.completions.create(
    model="kani/premium",  # always use best-quality models
    messages=[{"role": "user", "content": "prove P != NP"}],
)
```

### curl

```bash
curl http://localhost:18420/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model": "kani/auto", "messages": [{"role": "user", "content": "hello"}]}'
```

> **That's it.** Any tool or library that supports the OpenAI API works with kani — LangChain, LlamaIndex, Cursor, Continue, etc. Just point `base_url` at kani.

## Routing profiles

> Note: The routing profiles below are sample/reference defaults. Treat them as examples — you should tune the actual profile names, strategies, and model mappings to match your own workload and cost/quality goals.

| Profile | Strategy | Best for |
|---------|----------|----------|
| `kani/auto` | Balanced cost/quality (default) | General use |
| `kani/eco` | Cheapest viable models | High volume, low stakes |
| `kani/premium` | Best quality models | Critical tasks |
| `kani/agentic` | Tool-use optimized | Agent workflows |

## Capability-aware routing

kani automatically detects required capabilities from the request and routes to a model that supports them. If no model in the scored tier has the required capabilities, kani escalates to higher tiers.

**Detected capabilities:**

| Capability | Trigger |
|------------|---------|
| `vision` | `image_url` content block in messages |
| `tools` | `tools` or `functions` field in request |
| `json_mode` | `response_format.type` is `json_object` or `json_schema` |

**Configuration:** declare model capabilities via prefix matching in `config.yaml`:

```yaml
model_capabilities:
  - prefix: "anthropic/claude-"
    capabilities: [vision, tools, json_mode]
  - prefix: "google/gemini-"
    capabilities: [vision, tools, json_mode]
  - prefix: "openai/gpt-4"
    capabilities: [vision, tools, json_mode]
```

When no `model_capabilities` are configured, capability filtering is skipped and routing works as before.

## API endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/v1/chat/completions` | POST | Main proxy (OpenAI-compatible) |
| `/v1/models` | GET | List available models |
| `/v1/route` | POST | Debug — returns routing decision without proxying |
| `/admin/reload-config` | POST | Admin-only safe config hot reload |
| `/health` | GET | Health + active config version metadata |

Routed responses include extra headers: `X-Kani-Tier`, `X-Kani-Model`, `X-Kani-Score`, `X-Kani-Signals`.

## Configuration

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
  cliproxy:
    name: cliproxy
    base_url: "http://127.0.0.1:8317/v1"
    api_key: "local-test-key"

profiles:
  auto:
    tiers:
      SIMPLE:
        # primary can be a single model or an ordered list for round-robin
        primary: ["google/gemini-2.5-flash", "google/gemini-2.5-flash-lite"]
        fallback: ["nvidia/gpt-oss-120b"]
      MEDIUM:
        primary: "moonshotai/kimi-k2.5"
        fallback: null  # allowed; normalized to []
      COMPLEX:
        primary: "google/gemini-3.1-pro"
        fallback: ["anthropic/claude-sonnet-4.6"]
      REASONING:
        primary: "x-ai/grok-4-1-fast-reasoning"
        fallback: ["anthropic/claude-sonnet-4.6"]
      # provider: per-tier override (optional)

smart_proxy:
  fallback_backoff:
    enabled: true
    initial_delay_seconds: 5
    multiplier: 2
    max_delay_seconds: 300

# LLM classifier for low-confidence escalation (optional)
llm_classifier:
  model: "google/gemini-2.5-flash-lite"
  base_url: "https://openrouter.ai/api/v1"
  api_key: "${OPENROUTER_API_KEY}"
```

- `${VAR}` syntax resolves environment variables
- Each tier can specify its own `provider` or inherit `default_provider`
- `primary` accepts a string, `{model, provider}` object, or a list of those; list entries are selected **round-robin** per `profile+tier` combination
- `fallback: null` is accepted only at `profiles.*.tiers.*.fallback` and normalized to `[]`
- When primary fails, fallback attempts skip the failed primary candidate and deduplicate repeated `model+provider` entries
- `smart_proxy.fallback_backoff` enables process-local exponential cooldowns for retryable non-streaming `429` / `5xx` failures, keyed by `model+provider`
- Cooled-down `model+provider` pairs are skipped during both primary selection and fallback execution; the same model on a different provider remains eligible
- Successful recovery resets the failure streak for that exact `model+provider` pair, and restarting kani clears the in-memory cooldown registry
- Config path: `--config` flag > `$KANI_CONFIG` env var > `./config.yaml` > `$XDG_CONFIG_HOME/kani/config.yaml` > `/etc/kani/config.yaml`
- Set `KANI_ADMIN_TOKEN` to enable `POST /admin/reload-config` (admin-only, separate from regular API keys)
- Hot reload validates with `strict=True` and rejects non-reloadable field changes (`host`, `port`) with `409`

## Smart-proxy context compaction

kani can optionally reduce context pressure for long-running conversations by compacting oversized message histories before proxying upstream (Phase A) and by pre-computing summaries in the background for reuse on later requests (Phase B).

All compaction behavior is **opt-in and disabled by default**. When disabled or when compaction fails, kani routes and proxies requests unchanged.

### Configuration

Add a `smart_proxy` section to your `config.yaml`:

```yaml
smart_proxy:
  context_compaction:
    enabled: true                        # master switch

    sync_compaction:
      enabled: true                      # Phase A: compact inline before proxying
      threshold_percent: 80.0            # compact when prompt ≥ 80% of context window
      protect_first_n: 1                 # turns to keep at head of conversation
      protect_last_n: 2                  # turns to keep at tail
      summary_model: ""                  # empty = use 'compress' profile primary model

    background_precompaction:
      enabled: true                      # Phase B: pre-compute summaries async
      trigger_percent: 70.0              # start background job at 70% usage
      max_concurrency: 2                 # max parallel background jobs
      summary_ttl_seconds: 3600

    session:
      header_name: X-Kani-Session-Id    # client header for explicit session binding

    context_window_tokens: 128000        # assumed context window for threshold math
```

A `compress` routing profile (see `config.example.yaml`) is used as the default summarisation model when `summary_model` is empty.

### Session identity

kani resolves a stable session key in this order:

1. **Explicit header** — value of `session.header_name` (preferred; required for Phase B cache hits)
2. **Derived** — deterministic hash of model + first/last message content

The resolution mode is surfaced in the `X-Kani-Compaction-Session` response header.

### Operator telemetry

Each routed response includes compaction headers:

| Header | Values | Meaning |
|--------|--------|---------|
| `X-Kani-Compaction` | `off` \| `skipped` \| `inline` \| `cached` \| `failed` | What compaction did |
| `X-Kani-Compaction-Session` | `explicit` \| `derived` | How session was resolved |
| `X-Kani-Compaction-Saved-Tokens` | integer | Estimated tokens saved |

Structured log fields are emitted at `INFO` level on every compaction decision. Failures are logged at `WARNING` level and never propagate to the client.

### Safe config hot reload (admin)

Use admin-only config hot reload without restarting the proxy:

```bash
# 1) set an admin token (separate from normal API keys)
export KANI_ADMIN_TOKEN="your-admin-token"

# 2) trigger reload after editing config.yaml
curl -X POST http://localhost:18420/admin/reload-config \
  -H "Authorization: Bearer ${KANI_ADMIN_TOKEN}"
```

Behavior:

- Reload is applied only when strict config validation succeeds.
- In-flight requests keep the state snapshot captured at request start.
- Changes to `host` / `port` are rejected as non-reloadable with `409` and require process restart.

### Docker Compose / local deployment

No additional services are required. Compaction state is persisted in SQLite under `$XDG_DATA_HOME/kani/compaction.db` (default: `~/.local/share/kani/compaction.db`). Override with `KANI_DATA_DIR`.

```bash
# Verify compaction is active after startup:
curl -s http://localhost:18420/health | jq .
# Inspect a routed request's compaction outcome:
curl -v -X POST http://localhost:18420/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "X-Kani-Session-Id: my-session-1" \
  -d '{"model":"kani/auto","messages":[{"role":"user","content":"hello"}]}' \
  2>&1 | grep -i "x-kani-compaction"
```

## LLM escalation

When the embedding classifier is uncertain or unavailable, kani asks a cheap LLM.

**Preferred: configure via `config.yaml`** (see `llm_classifier` section above).

Alternatively, use environment variables (overridden by config.yaml if both are set):

| Env var | Default | Description |
|---------|---------|-------------|
| `KANI_LLM_CLASSIFIER_MODEL` | `google/gemini-2.5-flash-lite` | Classifier model |
| `KANI_LLM_CLASSIFIER_BASE_URL` | `https://openrouter.ai/api/v1` | API endpoint |
| `KANI_LLM_CLASSIFIER_API_KEY` | `$OPENROUTER_API_KEY` | API key |

Cost: ~$0.0001 per escalation. Timeout: 2s.

## Routing logs

All decisions are logged to `$XDG_STATE_HOME/kani/log/routing-YYYY-MM-DD.jsonl` (default: `~/.local/state/kani/log/`):

```json
{"timestamp": "2025-03-21T19:50:00", "prompt_preview": "prove the Riemann...", "tier": "REASONING", "score": 0.8, "confidence": 0.8, "method": "llm", "agentic_score": 0.0}
```

Use these logs to expand training data, retrain the embedding classifier, and audit where the LLM fallback is still firing too often.

If your routing logs already contain explicit `agenticLabel` evidence, build a strict dataset directly:

```bash
uv run python scripts/build_agentic_dataset.py \
  --output data/agentic_training_prompts.json
```

This extractor only keeps records with explicit agentic evidence, deduplicates by prompt, and writes a clean JSON dataset for future agentic-classifier training.
Newer logs include the full `prompt` plus a truncated `prompt_preview`, and the extractor prefers the full prompt automatically.

If logs are still sparse and you need an initial bootstrap dataset, use the cheap LLM judge to label unlabeled prompts from the same logs:

```bash
uv run python scripts/bootstrap_agentic_dataset.py \
  --output data/agentic_training_prompts.json
```

The bootstrap flow merges four sources into one training file:
- explicit labels already present in routing logs
- built-in seed examples
- optional manual overrides / exclude lists
- cheap-LLM labels for remaining prompts

Useful options:
- `--seed-file seeds.json` — extra `{prompt, label}` examples
- `--overrides-file overrides.json` — force labels for known prompts
- `--exclude-file excludes.txt` — skip shorthand/noisy prompts like `.` or `y`
- `--model`, `--base-url`, `--api-key` — point the bootstrap judge at a specific classifier endpoint

To train an embedding-based agentic classifier from that dataset:

```bash
uv run python scripts/train_agentic_classifier.py \
  --data data/agentic_training_prompts.json \
  --output models
```

This writes `models/agentic_classifier.pkl` with the sklearn classifier, label encoder, embedding metadata, and class distribution.
When that file exists, kani automatically uses it at runtime for the `agentic` profile: high-confidence learned predictions are applied directly, and only low-confidence cases fall back to the cheap LLM judge.

## API key authentication

kani supports API key authentication to restrict proxy access. Keys are managed via the CLI and stored in `$XDG_DATA_HOME/kani/api_keys.json`.

**When no keys are configured, all requests pass through without authentication** (backward-compatible). As soon as one key is added, every API request must include a valid `Authorization: Bearer <key>` header.

```bash
# Create a key (auto-generated, shown once)
kani keys add hermes
#   kani-aBcDeFgH...  ← save this

# List keys (prefix only, secrets are not stored in plaintext)
kani keys list

# Remove a key by name or prefix
kani keys remove hermes
```

Using the key:

```bash
curl http://localhost:18420/v1/chat/completions \
  -H "Authorization: Bearer kani-aBcDeFgH..." \
  -H "Content-Type: application/json" \
  -d '{"model": "kani/auto", "messages": [{"role": "user", "content": "hello"}]}'
```

```python
client = OpenAI(
    base_url="http://localhost:18420/v1",
    api_key="kani-aBcDeFgH...",  # kani API key
)
```

`/health` and `/docs` are exempt from authentication. No server restart required — keys take effect immediately.

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

```
src/kani/
├── scorer.py    # model-first scoring (embedding + LLM fallback)
├── router.py    # Tier → model+provider mapping
├── proxy.py     # FastAPI OpenAI-compatible server
├── config.py    # YAML config loading, env var resolution
├── dirs.py      # XDG-compliant directory paths (config, data, logs)
├── logger.py    # JSONL routing log
└── cli.py       # Click CLI
```

## Development

```bash
uv sync
uv run pytest tests/ -q    # 176 tests
uv run ruff check src/
uv run pyright src/
```

## Credits

Scoring logic ported from [ClawRouter](https://github.com/BlockRunAI/ClawRouter) (MIT license).

## License

MIT
