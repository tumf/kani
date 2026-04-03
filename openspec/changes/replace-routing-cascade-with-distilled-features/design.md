# Design: Distilled Feature-Based Routing Classification

## Overview

This change replaces the current routing classifier cascade with a single feature-oriented architecture:

1. `tokenCount` is computed deterministically.
2. A learned multi-output classifier predicts 14 semantic dimensions for the prompt.
3. The runtime scorer converts the 15 features into a weighted aggregate score.
4. The aggregate score is mapped to `SIMPLE`, `MEDIUM`, `COMPLEX`, or `REASONING`.
5. `agenticTask` is converted into the public `agentic_score` field and reused by the router's agentic-profile escalation logic.

The LLM is no longer a runtime dependency for routing decisions. It is only used offline to annotate training data for the 14 semantic dimensions.

## Goals

- Remove runtime dependence on tier/agentic LLM fallback.
- Replace direct class labels with explainable feature dimensions.
- Unify agentic scoring with the main classification pathway.
- Turn routing logs into a reusable supervision source.

## Non-Goals

- Japanese-first heuristics or language-specific rule systems.
- Online retraining or auto-tuning of weights.
- Supporting both old and new classification systems simultaneously.

## Feature Model

### Deterministic feature

- `tokenCount`

### Learned semantic dimensions

- `codePresence`
- `reasoningMarkers`
- `technicalTerms`
- `creativeMarkers`
- `simpleIndicators`
- `multiStepPatterns`
- `questionComplexity`
- `imperativeVerbs`
- `constraintCount`
- `outputFormat`
- `referenceComplexity`
- `negationComplexity`
- `domainSpecificity`
- `agenticTask`

Each semantic dimension is modeled as an ordinal value derived from `low`, `medium`, or `high` labels.

## Runtime Architecture

### Scorer

`src/kani/scorer.py` becomes responsible for:

- loading the distilled feature model bundle
- computing deterministic token counts
- embedding the prompt once
- predicting the 14 semantic dimensions
- mapping ordinal feature outputs into numeric values
- computing weighted aggregate score and tier
- exposing feature evidence in `ClassificationResult.signals` / `dimensions`
- deriving `agentic_score` from `agenticTask`

Runtime scorer must not call any LLM classifier or separate agentic classifier.

### Router

`src/kani/router.py` keeps existing profile, capability, and fallback behavior, but its classification input changes:

- tier is read from the new feature-based scorer
- `agentic_score` is always available from the same result object
- agentic profile SIMPLE→MEDIUM promotion remains, but it uses unified `agentic_score`

## Training Architecture

### Dataset generation

A training-data pipeline reads routing JSONL logs and produces structured records containing:

- prompt
- token count
- 14 semantic labels (`low|medium|high`)
- source metadata and timestamp

The semantic labels are produced by an offline LLM annotation step. This is distillation only.

### Model training

The training pipeline should:

1. read the structured feature dataset
2. embed prompts with the project's embedding provider
3. train a multi-output classifier for the 14 semantic dimensions
4. persist a model bundle with label metadata, embedding model name, and feature schema version

The existing direct tier and binary agentic bundles are retired.

## Logging and Introspection

Routing logs must remain append-only JSONL and continue to be non-blocking on write failure.

The logged payload should include enough data to support future retraining and debugging:

- classification method identifier for the feature-based runtime
- public tier / confidence / agentic score
- per-dimension feature payload or equivalent evidence structure

## Migration Notes

This is a hard replacement, not a dual-run migration.

Required migration updates:

- remove or redirect tests that assume embedding→LLM cascade behavior
- remove or redirect tests that assume independent agentic gating only on SIMPLE prompts
- update specs and docs to describe distilled feature routing as the canonical behavior

## Risks and Mitigations

### Risk: Feature labels drift from intended semantics

Mitigation:
- enforce a strict annotation schema
- keep dimension definitions explicit in code/tests/docs
- validate dataset generation deterministically where possible

### Risk: Weighted synthesis is poorly calibrated

Mitigation:
- keep weights explicit and versioned
- add tests for tier thresholds and representative prompts
- revisit weights after production log review

### Risk: Loss of fallback safety from removing runtime LLM

Mitigation:
- require a conservative default behavior when the feature model is unavailable
- keep log visibility for model load and scoring failures
