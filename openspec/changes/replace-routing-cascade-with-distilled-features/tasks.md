## Implementation Tasks

- [x] 1. Replace scorer runtime pipeline with a distilled feature model in `src/kani/scorer.py` (verification: `src/kani/scorer.py` no longer contains runtime `LLMClassifier`, `AgenticClassifier`, or direct tier/agentic cascade wiring; `ClassificationResult` still exposes `tier`, `confidence`, `agentic_score`, and feature explanation payloads)
- [x] 2. Rewire router integration in `src/kani/router.py` to consume feature-based classification only (verification: `src/kani/router.py` derives tier and `agentic_score` from the unified feature result and still preserves agentic profile SIMPLE→MEDIUM escalation behavior)
- [x] 3. Add a training-data generation pipeline for distilled semantic dimensions from routing logs (verification: repository contains code and tests that turn `routing-*.jsonl` prompts into structured feature-label datasets with the 14 semantic dimensions plus deterministic token counts)
- [x] 4. Add a training pipeline for the multi-output feature classifier and retire direct tier/agentic model bundles (verification: repository contains a training entrypoint that writes a new feature-model bundle, and obsolete direct tier / agentic training entrypoints and model assumptions are removed or redirected)
- [x] 5. Update routing logs and related tests to persist feature-based evidence for later distillation (verification: tests cover that routing logs capture method plus feature payloads needed for replay/training without breaking existing JSONL write guarantees)
- [x] 6. Update routing tests and training tests for the new architecture (verification: `uv run pytest tests/ -q` covers feature-based tier selection, unified agentic score behavior, training-data generation, and logging shape)
- [x] 7. Update docs/spec references for the new routing classifier architecture (verification: OpenSpec deltas and any affected repository docs mention distilled feature-based classification rather than embedding→LLM cascade)
- [x] 8. Run repository quality gates after the replacement (verification: `uv run ruff check src/`, `uv run ruff format --check src/ tests/`, `uv run pyright src/`, `uv run pytest tests/ -q`, and `uv build` all pass)

## Future Work

- Recalibrate feature weights and tier thresholds with production log analysis after enough post-migration data accumulates.
- Consider optional multilingual calibration if non-English routing quality becomes a product requirement.
