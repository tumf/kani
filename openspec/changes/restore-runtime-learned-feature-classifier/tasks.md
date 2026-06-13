## Implementation Tasks

- [ ] Restore the runtime distilled feature classifier adapter in `src/kani/scorer.py` so it loads `feature_classifier.pkl`, validates required bundle fields, stores `feature_model_dir`, and caches load attempts without treating file presence alone as activation (verification: unit - `uv run pytest tests/test_scorer.py -q -k "feature_model_dir or load_failure or missing_model"`).
- [ ] Restore runtime embedding-backed semantic prediction in `src/kani/scorer.py` using configured embedding resolution and the model bundle's `embedding_model`, then decode per-dimension labels through bundle label encoders (verification: unit - `uv run pytest tests/test_scorer.py -q -k "distilled_features or embedding"`).
- [ ] Ensure learned-classifier success builds classification results from learned semantic labels, bundle weights, and bundle tier thresholds with `signals.method.raw == "distilled-features"` and 15 dimensions (verification: unit - `uv run pytest tests/test_scorer.py -q -k distilled_features`).
- [ ] Ensure every unavailable/failure path returns the configured conservative default fallback and never calls `_heuristic_semantic_labels()` or equivalent keyword fallback from `Scorer.classify()` (verification: unit - `uv run pytest tests/test_scorer.py -q -k "default_fallback or no_heuristic"`).
- [ ] Update `kani doctor` classifier asset diagnostics in `src/kani/cli.py` so `feature_classifier.pkl` is reported consistently with explicit runtime loading evidence while not claiming activation from file presence alone (verification: unit - `uv run pytest tests/test_cli.py -q -k doctor_feature_classifier_runtime_status`).
- [ ] Update documentation only if implementation changes alter the described runtime classifier behavior or doctor output wording (verification: manual - inspect `README.md` and `CONTRIBUTING.md`, then compare their classifier and doctor descriptions against `src/kani/scorer.py` and `src/kani/cli.py`).
- [ ] Run repository quality gates after implementation (verification: integration - `uv run ruff check src/ && uv run ruff format --check src/ tests/ && uv run pyright src/ && uv run pytest tests/ -q`).

## Future Work

- Recalibrate or retrain `models/feature_classifier.pkl` if restored runtime tests reveal that the existing bundle schema or labels are incompatible with current semantic dimensions.
- Add optional operational metrics for embedding latency or classifier availability if runtime embedding cost becomes an observability concern.

## Final Validation

Archive validation itself is the authoritative final OpenSpec validation gate.
Expected archive gate: `cflx openspec validate restore-runtime-learned-feature-classifier --archive-gate`.
