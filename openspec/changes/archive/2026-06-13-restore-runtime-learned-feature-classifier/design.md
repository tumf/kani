# Design: Restore runtime learned feature classifier

## Background

The current training pipeline writes `models/feature_classifier.pkl` with a multi-output classifier, label encoders, embedding metadata, scoring weights, thresholds, and feature schema metadata. Runtime routing previously had a `DistilledFeatureClassifier` adapter that loaded this bundle and predicted the 14 semantic dimensions from prompt embeddings.

Commit `5619653` removed that runtime embedding dependency and replaced runtime semantic labels with heuristics. This proposal restores the learned runtime path because the canonical routing behavior requires learned semantic dimensions when the model is available.

## Runtime Flow

1. `Scorer.classify(text)` lazily attempts to load the feature model once per configured model directory.
2. `DistilledFeatureClassifier.load(model_dir)` resolves `feature_classifier.pkl` from `feature_model_dir` or the repository `models/` directory.
3. The model bundle is validated before use:
   - required keys exist
   - semantic dimensions match `SEMANTIC_DIMENSIONS`
   - label encoders exist for all semantic dimensions
   - classifier exposes prediction APIs required by runtime
4. Prediction computes an embedding for the prompt using configured embedding resolution and the bundle's embedding model, under an explicit bounded timeout. Exceeding the timeout is treated as an embedding failure and converges to the default fallback (analogous to the existing 2s LLM-classifier bound).
5. The multi-output classifier predicts encoded labels, which are decoded through per-dimension label encoders.
6. `Scorer` computes dimensions, score, tier, confidence, and `agentic_score` from learned labels and bundle scoring metadata.
7. Successful results use `signals.method.raw == "distilled-features"`.

## Failure Semantics

All classifier-unavailable cases converge to conservative default fallback:

- missing `feature_classifier.pkl`
- invalid or incompatible pickle bundle
- embedding config unavailable or disabled
- embedding API failure
- classifier prediction failure
- label decode failure

The failure path must not call heuristic semantic labeling. This keeps routing auditable and avoids silently substituting a different classifier family.

## Doctor Diagnostics

`kani doctor` should remain read-only and static. To report runtime-loading support without fragile source-code scanning, the scorer module SHOULD expose a stable capability marker (e.g. a module-level constant such as `RUNTIME_FEATURE_CLASSIFIER_SUPPORTED = True`, or the importable `DistilledFeatureClassifier` symbol itself) that `doctor` reads. `doctor` then reports three distinct states for `feature_classifier.pkl`:

- runtime support present **and** asset exists → loadable but not proven active (no embedding call is made),
- runtime support present **and** asset missing/unloadable → warn: default-only routing mode,
- runtime support absent → asset is unused by the current runtime.

`doctor` MUST NOT perform embedding calls or claim the model is active solely because the file exists.

## Security / Trust Boundary

`feature_classifier.pkl` is deserialized with `pickle.load` inside the long-running proxy process, which executes arbitrary code embedded in the pickle. The model file is operator-provided and trusted at the same level as `config.yaml`. The loader MUST resolve the bundle only from the configured `feature_model_dir` or the repository `models/` directory and MUST NOT accept classifier paths from request-scoped or otherwise untrusted input.

## Bundle Compatibility Precondition

Before relying on the existing `models/feature_classifier.pkl`, the change verifies the committed bundle actually unpickles and predicts under the current `scikit-learn`/`numpy` versions and that `embedding_dim` / `semantic_dimensions` match the runtime `SEMANTIC_DIMENSIONS`. If the committed bundle is incompatible, that is surfaced as an explicit blocker rather than silently triggering the out-of-scope retraining path.

## Trade-offs

- Restoring runtime embedding can add network latency and depends on embedding credentials/configuration.
- The safe fallback preserves routing availability when the learned classifier cannot run.
- Avoiding heuristic fallback makes classifier unavailability more visible and keeps runtime behavior aligned with the canonical spec.
