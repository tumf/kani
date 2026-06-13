---
change_type: implementation
priority: high
dependencies: []
references:
  - https://github.com/tumf/kani/issues/7
  - src/kani/scorer.py
  - src/kani/router.py
  - src/kani/cli.py
  - src/kani/feature_training.py
  - tests/test_scorer.py
  - tests/test_cli.py
  - openspec/specs/routing/spec.md
  - openspec/specs/config/spec.md
---

# Restore runtime learned feature classifier

**Change Type**: implementation

## Premise / Context

- Issue #7 reports that `models/feature_classifier.pkl` is trained and documented as the runtime distilled feature model, but current routing uses heuristic semantic labels instead.
- Commit `5619653` removed the runtime embedding/pickle classifier path from `src/kani/scorer.py` to remove runtime embedding dependency from routing.
- The canonical routing spec still requires deterministic `tokenCount` plus learned 14 semantic dimensions when the distilled feature model is available.
- The desired behavior is to restore learned runtime classification and explicitly avoid heuristic runtime fallback.
- The canonical `openspec/specs/routing/spec.md` is currently internally inconsistent: it contains duplicate `### Requirement: ティア分類カスケード` headers (one describing the legacy 3-layer embedding→LLM→default cascade, one describing the distilled-features classifier), duplicate `LLM 分類器の動作` / `分類結果の構造` / `メッセージ解析` / `Agentic 分類` requirements, and a stray bare `#` separator. A `MODIFIED` operation targeting `ティア分類カスケード` is ambiguous against two same-named requirements, so this change MUST normalize the canonical spec (dedupe requirement headers, remove the stray separator) before/while modifying the cascade requirement.
- Current runtime reality to restore against: `Scorer.classify()` emits `signals.method.raw == "heuristic-features"` (not `default`) and `Scorer.__init__()` accepts but silently ignores `feature_model_dir`. No `DistilledFeatureClassifier` adapter exists in the runtime today.

## Problem

Kani currently routes prompts through `_heuristic_semantic_labels()` in `Scorer._classify_with_features()`. This diverges from the canonical routing spec and README, which describe a distilled-feature classifier that loads `feature_classifier.pkl`, embeds the prompt, predicts 14 semantic dimensions, and emits `signals.method=distilled-features`.

The current behavior is also operationally ambiguous: `feature_classifier.pkl` exists and training code writes it, but runtime routing does not load it. This can cause users and operators to believe a learned classifier is active when routing is actually keyword-based.

## Proposed Solution

Restore the runtime learned feature classifier path in `src/kani/scorer.py`:

- Load `models/feature_classifier.pkl` or `feature_model_dir/feature_classifier.pkl` through an explicit `DistilledFeatureClassifier` runtime adapter.
- Use configured embedding settings to compute prompt embeddings at runtime.
- Predict the 14 semantic dimensions through the trained multi-output classifier.
- Use model-bundle `weights` and `tier_thresholds` for score and tier calculation.
- Return `signals.method.raw == "distilled-features"` only when model loading and prediction succeed.
- Map the bundle's `feature_schema_version` value into `signals.featureVersion` (the field names differ between bundle and runtime signal and the mapping MUST be explicit).
- Bound the runtime embedding call with an explicit timeout; on timeout return the conservative default fallback (mirroring the existing 2s LLM-classifier bound in the routing spec).
- If model loading, bundle validation, embedding configuration, embedding API calls, embedding timeout, or prediction fails, return the conservative default fallback.
- Do not use heuristic semantic labels as a runtime fallback.

## Key Decisions / Risks

- **Default/untrained-install behavior change (intentional, must be visible).** Today an install without a trained model still routes via heuristics. With heuristics removed and failure converging to `default`, an install that lacks a usable `feature_classifier.pkl` **or** embedding credentials will route every prompt to `tier=MEDIUM, confidence=0.35`. This is the expected out-of-the-box state for most users. The constitution prohibits heuristic runtime classification, so this is accepted — but the change MUST surface it: `kani doctor` MUST clearly warn when the feature classifier is absent/unloadable, and the server SHOULD log a single startup warning that routing is operating in default-only mode.
- **Embedding on the hot path.** Restoring runtime embedding adds per-request latency, cost, and a network dependency to routing. Mitigated by the bounded timeout above and the conservative default fallback.
- **Pickle trust boundary.** `feature_classifier.pkl` is loaded via `pickle.load` inside the proxy server process, which is an arbitrary-code-execution surface. The model file is operator-provided and trusted at the same level as `config.yaml`; the change MUST NOT load classifier bundles from untrusted or user-writable locations beyond the configured model directory.

Update `kani doctor` classifier diagnostics so the feature classifier asset is no longer described as unused once explicit runtime loading evidence exists, while still avoiding claims that file presence alone means the classifier is active.

## Acceptance Criteria

- Runtime routing loads `feature_classifier.pkl` when available and predicts semantic dimensions through the learned classifier.
- Successful learned classification returns `signals.method.raw == "distilled-features"` and includes `tokenCount`, `semanticLabels`, `featureVersion`, and 15 dimension results.
- `Scorer(feature_model_dir=...)` reads the model from the supplied directory.
- Missing model, invalid pickle bundle, embedding configuration failure, embedding API failure, embedding timeout, or classifier prediction failure returns the configured default fallback with `signals.method.raw == "default"`.
- The runtime embedding call is bounded by an explicit timeout, and exceeding it returns the default fallback rather than blocking routing.
- Runtime routing never falls back to `_heuristic_semantic_labels()` or equivalent keyword semantic labels.
- `kani doctor` reports `feature_classifier.pkl` consistently with restored runtime loading behavior, does not mark it active based on file presence alone, and clearly warns when the classifier is absent or unloadable (default-only routing mode).
- The existing `models/feature_classifier.pkl` is verified to load and predict under the current runtime dependency versions (or the incompatibility is documented and escalated), so "restore" does not silently depend on out-of-scope retraining.
- Tests cover success, missing model, load failure, embedding failure, prediction failure, and no-heuristic-fallback behavior.

## Explicit Completion Conditions

- `src/kani/scorer.py` contains an explicit runtime model loading path for `feature_classifier.pkl`, an embedding-backed prediction path, and a default-only failure path.
- `Scorer.__init__()` stores and uses `feature_model_dir` for model discovery.
- Existing heuristic semantic label logic is removed from the runtime `Scorer.classify()` path or is guarded by tests proving it is not invoked as fallback.
- `tests/test_scorer.py` includes behavioral tests using mocks/stubs that fail if routing silently uses heuristic labels, and a test asserting the embedding timeout path returns the default fallback.
- `tests/test_cli.py` covers the updated doctor classifier asset message, including the absent/unloadable (default-only) warning.
- `openspec/specs/routing/spec.md` no longer contains duplicate requirement headers or the stray `#` separator, and `openspec validate restore-runtime-learned-feature-classifier --strict` passes.
- Relevant quality gates pass: `uv run ruff check src/`, `uv run ruff format --check src/ tests/`, `uv run pyright src/`, and `uv run pytest tests/ -q`.

## Out of Scope

- Retraining or replacing `models/feature_classifier.pkl`.
- Reintroducing legacy `tier_classifier.pkl` routing.
- Adding heuristic runtime fallback.
- Changing the public OpenAI-compatible proxy request or response shape.
- Adding real network probes to `kani doctor`.
