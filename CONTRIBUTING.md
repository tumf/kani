# Contributing to kani

## Architecture

```
src/kani/
├── scorer.py           # distilled feature scoring (runtime)
├── feature_training.py # multi-output feature model training
├── training_data.py    # distilled feature dataset generation
├── router.py           # Tier → model+provider mapping
├── proxy.py            # FastAPI OpenAI-compatible server
├── config.py           # YAML config loading, env var resolution
├── logger.py           # JSONL routing log
└── cli.py              # Click CLI
```

## Classification pipeline

Unified distilled-feature pipeline:

1. **Token count** — deterministic `tokenCount` extraction
2. **Semantic classifier** — learned multi-output classifier predicts 14 semantic dimensions (`low` / `medium` / `high`)
3. **Weighted synthesis** — all 15 dimensions are aggregated into one routing score
4. **Tier mapping** — score maps to `SIMPLE` / `MEDIUM` / `COMPLEX` / `REASONING`
5. **Unified agentic score** — `agenticTask` dimension maps directly to `agentic_score`
6. **Conservative default** — fallback to `MEDIUM` only when the feature model is unavailable

Runtime scorer intentionally avoids runtime LLM fallback and separate agentic classifier paths.

## Routing logs

All decisions are logged to `$XDG_STATE_HOME/kani/log/routing-YYYY-MM-DD.jsonl`:

```json
{
  "timestamp": "2026-03-21T19:50:00+00:00",
  "prompt_preview": "prove the Riemann...",
  "tier": "REASONING",
  "score": 0.82,
  "confidence": 0.87,
  "method": "distilled-features",
  "agentic_score": 1.0,
  "signals": {
    "tokenCount": 38,
    "semanticLabels": {
      "reasoningMarkers": "high",
      "agenticTask": "high"
    },
    "featureVersion": "v1"
  }
}
```

## Distilled feature dataset generation

Build training data from routing logs:

```bash
uv run python scripts/build_agentic_dataset.py --output data/distilled_feature_dataset.json
```

If logs are missing semantic labels, add `--annotate-missing` to run offline LLM annotation.
LLM annotation is for dataset generation only (not runtime routing).

## Feature model training

Train the multi-output classifier bundle:

```bash
uv run python scripts/train_classifier.py \
  --data data/distilled_feature_dataset.json \
  --output models
```

This writes `models/feature_classifier.pkl` with:

- sklearn multi-output classifier
- per-dimension label encoders
- embedding metadata
- default feature weights and tier thresholds
- feature schema version

## Response headers

Routed responses include extra headers for debugging:

- `X-Kani-Tier` — classified tier (SIMPLE / MEDIUM / COMPLEX / REASONING)
- `X-Kani-Model` — actual model selected
- `X-Kani-Score` — raw weighted score
- `X-Kani-Signals` — signal payload summary

## Development

```bash
uv sync
uv run pytest tests/ -q
uv run ruff check src/
uv run pyright src/
```

## Credits

Scoring logic ported from [ClawRouter](https://github.com/BlockRunAI/ClawRouter) (MIT license).
