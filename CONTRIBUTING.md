# Contributing to kani

## Architecture

```
src/kani/
├── scorer.py    # model-first scoring (embedding + LLM fallback)
├── router.py    # Tier → model+provider mapping
├── proxy.py     # FastAPI OpenAI-compatible server
├── config.py    # YAML config loading, env var resolution
├── logger.py    # JSONL routing log
└── cli.py       # Click CLI
```

## Classification pipeline

3-layer cascade:

1. **Embedding classifier** — pre-trained sklearn model for tier routing (primary path)
2. **LLM-as-judge** — cheap fallback for uncertain or unavailable tier decisions
3. **Agentic embedding classifier** — for the `agentic` profile, SIMPLE prompts get a learned AGENTIC / NON_AGENTIC pass when `models/agentic_classifier.pkl` exists
4. **Agentic LLM fallback** — only used when the learned agentic classifier is uncertain or unavailable
5. **Conservative default** — fall back to `MEDIUM` when neither classifier can decide

The scorer intentionally avoids hand-maintained keyword tables. If routing quality is off, prefer improving training data, retraining the embedding model, or tightening the LLM classifier prompt instead of adding heuristics.

## LLM escalation

When the learned tier classifier isn't confident enough, kani asks a cheap LLM:

| Env var | Default | Description |
|---------|---------|-------------|
| `KANI_LLM_CLASSIFIER_MODEL` | `google/gemini-2.5-flash-lite` | Classifier model |
| `KANI_LLM_CLASSIFIER_BASE_URL` | `https://openrouter.ai/api/v1` | API endpoint |
| `KANI_LLM_CLASSIFIER_API_KEY` | `$OPENROUTER_API_KEY` | API key |

Cost: ~$0.0001 per escalation. Timeout: 2s.

## Routing logs

All decisions are logged to `$XDG_STATE_HOME/kani/log/routing-YYYY-MM-DD.jsonl`:

```json
{"timestamp": "2025-03-21T19:50:00", "prompt_preview": "prove the Riemann...", "tier": "REASONING", "score": 0.8, "confidence": 0.8, "method": "llm", "agentic_score": 0.0}
```

Use `uv run python scripts/build_agentic_dataset.py --output data/agentic_training_prompts.json` to extract binary AGENTIC / NON_AGENTIC examples from routing logs.
The extractor only keeps records with explicit agentic evidence, prefers full `prompt` when present, and deduplicates by prompt.

Use `uv run python scripts/train_agentic_classifier.py --data data/agentic_training_prompts.json --output models` to train an embedding-based binary agentic classifier and save `models/agentic_classifier.pkl`.

At runtime, kani loads `models/agentic_classifier.pkl` automatically for the `agentic` profile. High-confidence learned predictions are used directly; low-confidence cases fall back to the cheap LLM judge.

## Response headers

Routed responses include extra headers for debugging:

- `X-Kani-Tier` — classified tier (SIMPLE / MEDIUM / COMPLEX / REASONING)
- `X-Kani-Model` — actual model selected
- `X-Kani-Score` — raw weighted score
- `X-Kani-Signals` — triggered dimensions

## Development

```bash
uv sync
uv run pytest tests/ -q    # 42 tests
uv run ruff check src/
uv run pyright src/
```

## Credits

Scoring logic ported from [ClawRouter](https://github.com/BlockRunAI/ClawRouter) (MIT license).
