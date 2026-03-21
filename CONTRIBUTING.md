# Contributing to kani

## Architecture

```
src/kani/
├── scorer.py    # 15-dimension scoring + embedding + LLM classifier
├── router.py    # Tier → model+provider mapping
├── proxy.py     # FastAPI OpenAI-compatible server
├── config.py    # YAML config loading, env var resolution
├── logger.py    # JSONL routing log
└── cli.py       # Click CLI
```

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

## Classification pipeline

3-layer cascade:

1. **Embedding classifier** — pre-trained sklearn model (if available)
2. **Rules engine** — 15-dimension weighted scoring (ClawRouter port, MIT)
3. **LLM-as-judge** — cheap LLM escalation when rules confidence < 0.7

## LLM escalation

When the rules engine isn't confident (< 0.7), kani asks a cheap LLM:

| Env var | Default | Description |
|---------|---------|-------------|
| `KANI_LLM_CLASSIFIER_MODEL` | `google/gemini-2.5-flash-lite` | Classifier model |
| `KANI_LLM_CLASSIFIER_BASE_URL` | `https://openrouter.ai/api/v1` | API endpoint |
| `KANI_LLM_CLASSIFIER_API_KEY` | `$OPENROUTER_API_KEY` | API key |

Cost: ~$0.0001 per escalation. Timeout: 2s.

## Routing logs

All decisions are logged to `$XDG_STATE_HOME/kani/log/routing-YYYY-MM-DD.jsonl`:

```json
{"timestamp": "2025-03-21T19:50:00", "prompt_preview": "prove the Riemann...", "tier": "REASONING", "score": 0.1, "confidence": 0.85, "method": "rules", "agentic_score": 0.0}
```

Future: train an embedding classifier from these logs to replace the heuristic rules.

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
