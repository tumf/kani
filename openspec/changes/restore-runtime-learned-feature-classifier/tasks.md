## Implementation Tasks

- [ ] Precondition: verify the committed `models/feature_classifier.pkl` unpickles and predicts under current `scikit-learn`/`numpy`, and that `embedding_dim` / `semantic_dimensions` match runtime `SEMANTIC_DIMENSIONS`; if incompatible, escalate as a blocker instead of entering out-of-scope retraining (verification: unit - `uv run pytest tests/test_scorer.py -q -k "bundle_compat or bundle_schema"`).
- [ ] Normalize `openspec/specs/routing/spec.md`: remove the stray `#` separator and dedupe the duplicate requirement headers (`ティア分類カスケード`, `LLM 分類器の動作`, `分類結果の構造`, `メッセージ解析`, `Agentic 分類`) so the distilled-features cascade is the single authoritative requirement (verification: integration - `cflx openspec validate restore-runtime-learned-feature-classifier --strict`).
- [ ] Restore the runtime distilled feature classifier adapter in `src/kani/scorer.py` so it loads `feature_classifier.pkl`, validates required bundle fields, stores `feature_model_dir`, exposes a doctor-readable runtime-support marker, and caches load attempts without treating file presence alone as activation (verification: unit - `uv run pytest tests/test_scorer.py -q -k "feature_model_dir or load_failure or missing_model"`).
- [ ] Restore runtime embedding-backed semantic prediction in `src/kani/scorer.py` using configured embedding resolution and the model bundle's `embedding_model` under an explicit bounded timeout (timeout → default fallback), then decode per-dimension labels through bundle label encoders (verification: unit - `uv run pytest tests/test_scorer.py -q -k "distilled_features or embedding or embedding_timeout"`).
- [ ] Ensure learned-classifier success builds classification results from learned semantic labels, bundle weights, and bundle tier thresholds with `signals.method.raw == "distilled-features"` and 15 dimensions (verification: unit - `uv run pytest tests/test_scorer.py -q -k distilled_features`).
- [ ] Ensure every unavailable/failure path returns the configured conservative default fallback and never calls `_heuristic_semantic_labels()` or equivalent keyword fallback from `Scorer.classify()` (verification: unit - `uv run pytest tests/test_scorer.py -q -k "default_fallback or no_heuristic"`).
- [ ] Update `kani doctor` classifier asset diagnostics in `src/kani/cli.py` so `feature_classifier.pkl` is reported via the scorer's runtime-support marker (not source scanning), distinguishes loadable-but-not-active from absent/unloadable (default-only warning), and does not claim activation from file presence alone (verification: unit - `uv run pytest tests/test_cli.py -q -k "doctor_feature_classifier_runtime_status or doctor_feature_classifier_missing"`).
- [ ] Update documentation only if implementation changes alter the described runtime classifier behavior or doctor output wording (verification: manual - inspect `README.md` and `CONTRIBUTING.md`, then compare their classifier and doctor descriptions against `src/kani/scorer.py` and `src/kani/cli.py`).
- [ ] Run repository quality gates after implementation (verification: integration - `uv run ruff check src/ && uv run ruff format --check src/ tests/ && uv run pyright src/ && uv run pytest tests/ -q`).

## Future Work

- Recalibrate or retrain `models/feature_classifier.pkl` if restored runtime tests reveal that the existing bundle schema or labels are incompatible with current semantic dimensions.
- Add optional operational metrics for embedding latency or classifier availability if runtime embedding cost becomes an observability concern.

## Final Validation

Archive validation itself is the authoritative final OpenSpec validation gate.
Expected archive gate: `cflx openspec validate restore-runtime-learned-feature-classifier --archive-gate`.
