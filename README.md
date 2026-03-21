# 🦀 kani

[![CI](https://github.com/tumf/kani/actions/workflows/ci.yml/badge.svg)](https://github.com/tumf/kani/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

LLM smart router. Classifies prompts by complexity and routes to the optimal model.

OpenAI API-compatible proxy — drop in as a base URL and let kani pick the right model automatically.

## How it works

```
Request → 15-Dimension Scorer → Tier → Model Selection → Upstream Provider
                                  │
                  ┌────────────┬──┴──────────┬──────────────┐
                SIMPLE       MEDIUM       COMPLEX       REASONING
            gemini-flash    kimi-k2.5   gemini-pro    grok-reasoning
```

**Classification pipeline (3 layers):**

1. **Embedding classifier** — pre-trained sklearn model (if available)
2. **Rules engine** — 15-dimension weighted scoring (ClawRouter port, MIT)
3. **LLM-as-judge** — cheap LLM escalation when rules confidence < 0.7

Every request is logged to `$XDG_STATE_HOME/kani/log/` (default: `~/.local/state/kani/log/`) as training data for future model improvement.

## Scoring dimensions

| # | Dimension | Weight | What it detects |
|---|-----------|--------|-----------------|
| 1 | tokenCount | 0.08 | Prompt length via tiktoken |
| 2 | codePresence | 0.15 | `function`, `class`, `import`, `` ``` `` etc. |
| 3 | reasoningMarkers | 0.18 | `prove`, `theorem`, `step by step` etc. |
| 4 | technicalTerms | 0.10 | `algorithm`, `kubernetes`, `architecture` etc. |
| 5 | creativeMarkers | 0.05 | `story`, `poem`, `brainstorm` etc. |
| 6 | simpleIndicators | 0.02 | `what is`, `hello`, `translate` (negative weight) |
| 7 | multiStepPatterns | 0.12 | `first...then`, `step 1`, numbered lists |
| 8 | questionComplexity | 0.05 | Multiple `?` in prompt |
| 9 | imperativeVerbs | 0.03 | `build`, `implement`, `deploy` etc. |
| 10 | constraintCount | 0.04 | `must`, `ensure`, `require` etc. |
| 11 | outputFormat | 0.03 | `json`, `csv`, `markdown` etc. |
| 12 | referenceComplexity | 0.02 | `according to`, `based on` etc. |
| 13 | negationComplexity | 0.01 | `not`, `without`, `except` etc. |
| 14 | domainSpecificity | 0.02 | `medical`, `legal`, `financial` etc. |
| 15 | agenticTask | 0.04 | `read file`, `execute`, `deploy`, `debug` etc. |

Multilingual — English and Japanese keywords included.

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

| Profile | Strategy | Best for |
|---------|----------|----------|
| `kani/auto` | Balanced cost/quality (default) | General use |
| `kani/eco` | Cheapest viable models | High volume, low stakes |
| `kani/premium` | Best quality models | Critical tasks |
| `kani/agentic` | Tool-use optimized | Agent workflows |

## API endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/v1/chat/completions` | POST | Main proxy (OpenAI-compatible) |
| `/v1/models` | GET | List available models |
| `/v1/route` | POST | Debug — returns routing decision without proxying |
| `/health` | GET | Health check |

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
        primary: "google/gemini-2.5-flash"
        fallback: ["google/gemini-2.5-flash-lite", "nvidia/gpt-oss-120b"]
      MEDIUM:
        primary: "moonshotai/kimi-k2.5"
        fallback: ["google/gemini-2.5-flash"]
      COMPLEX:
        primary: "google/gemini-3.1-pro"
        fallback: ["anthropic/claude-sonnet-4.6"]
      REASONING:
        primary: "x-ai/grok-4-1-fast-reasoning"
        fallback: ["anthropic/claude-sonnet-4.6"]
      # provider: per-tier override (optional)

# LLM classifier for low-confidence escalation (optional)
llm_classifier:
  model: "google/gemini-2.5-flash-lite"
  base_url: "https://openrouter.ai/api/v1"
  api_key: "${OPENROUTER_API_KEY}"
```

- `${VAR}` syntax resolves environment variables
- Each tier can specify its own `provider` or inherit `default_provider`
- Config path: `--config` flag > `$KANI_CONFIG` env var > `./config.yaml` > `$XDG_CONFIG_HOME/kani/config.yaml` > `/etc/kani/config.yaml`

## LLM escalation

When the rules engine isn't confident (< 0.7), kani asks a cheap LLM.

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
{"timestamp": "2025-03-21T19:50:00", "prompt_preview": "prove the Riemann...", "tier": "REASONING", "score": 0.1, "confidence": 0.85, "method": "rules", "agentic_score": 0.0}
```

Future: train an embedding classifier from these logs to replace the heuristic rules.

## CLI

```bash
kani serve [--config path] [--host 0.0.0.0] [--port 18420]
kani route "your prompt here" [--config path]
kani config [--config path]
```

## Architecture

```
src/kani/
├── scorer.py    # 15-dimension scoring + embedding + LLM classifier
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
uv run pytest tests/ -q    # 42 tests
uv run ruff check src/
uv run pyright src/
```

## Credits

Scoring logic ported from [ClawRouter](https://github.com/BlockRunAI/ClawRouter) (MIT license).

## License

MIT
