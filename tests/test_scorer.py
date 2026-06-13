"""Tests for kani distilled feature scoring engine."""

from __future__ import annotations

import pickle
import time
from pathlib import Path
from typing import Any
from unittest.mock import patch

import numpy as np

from kani.scorer import (
    DistilledFeatureClassifier,
    SEMANTIC_DIMENSIONS,
    ClassificationResult,
    Scorer,
    ScoringConfig,
    Tier,
    inspect_feature_classifier_runtime_status,
)


class _FakeClassifier:
    def __init__(self, encoded_label: int = 2, *, fail: bool = False) -> None:
        self.encoded_label = encoded_label
        self.fail = fail
        self.seen_shape: tuple[int, ...] | None = None

    def predict(self, embeddings: np.ndarray[Any, Any]) -> np.ndarray[Any, Any]:
        self.seen_shape = tuple(embeddings.shape)
        if self.fail:
            raise RuntimeError("prediction failed")
        return np.full((1, len(SEMANTIC_DIMENSIONS)), self.encoded_label)


class _FakeLabelEncoder:
    def inverse_transform(self, values: list[int]) -> list[str]:
        mapping = {0: "low", 1: "medium", 2: "high"}
        return [mapping[int(value)] for value in values]


class _FakeEmbeddings:
    def __init__(self, embedding: list[float], *, delay: float = 0.0) -> None:
        self.embedding = embedding
        self.delay = delay
        self.calls: list[dict[str, Any]] = []

    def create(self, *, input: list[str], model: str) -> Any:
        self.calls.append({"input": input, "model": model})
        if self.delay:
            time.sleep(self.delay)
        item = type("EmbeddingItem", (), {"embedding": self.embedding})()
        return type("EmbeddingResponse", (), {"data": [item]})()


class _FakeEmbeddingClient:
    def __init__(self, embedding: list[float], *, delay: float = 0.0) -> None:
        self.embeddings = _FakeEmbeddings(embedding, delay=delay)


def _bundle(*, classifier: Any | None = None, embedding_dim: int = 3) -> dict[str, Any]:
    return {
        "classifier": classifier or _FakeClassifier(),
        "label_encoders": {
            dimension: _FakeLabelEncoder() for dimension in SEMANTIC_DIMENSIONS
        },
        "semantic_dimensions": list(SEMANTIC_DIMENSIONS),
        "embedding_model": "text-embedding-test",
        "embedding_dim": embedding_dim,
        "training_size": 1,
        "class_distribution": {},
        "weights": {
            "tokenCount": 0.2,
            **{dimension: 1.0 for dimension in SEMANTIC_DIMENSIONS},
        },
        "tier_thresholds": {"SIMPLE": 0.2, "MEDIUM": 0.45, "COMPLEX": 0.7},
        "feature_schema_version": "test-v1",
    }


def _write_bundle(model_dir: Path, bundle: dict[str, Any] | None = None) -> Path:
    model_dir.mkdir(parents=True, exist_ok=True)
    model_path = model_dir / "feature_classifier.pkl"
    with model_path.open("wb") as f:
        pickle.dump(bundle or _bundle(), f)
    return model_path


class TestDistilledFeatureScorer:
    def test_bundle_schema_validates_current_semantic_dimensions(
        self, tmp_path
    ) -> None:
        model_path = _write_bundle(tmp_path)

        classifier = DistilledFeatureClassifier.load(tmp_path)

        assert classifier.model_path == model_path
        assert classifier.embedding_dim == 3
        assert tuple(classifier.label_encoders) == SEMANTIC_DIMENSIONS

    def test_bundle_compat_predicts_with_mock_embedding(self, tmp_path) -> None:
        fake_classifier = _FakeClassifier(encoded_label=1)
        _write_bundle(tmp_path, _bundle(classifier=fake_classifier))
        embedding_client = _FakeEmbeddingClient([0.1, 0.2, 0.3])

        with patch(
            "kani.scorer._resolve_runtime_embedding_client",
            return_value=(embedding_client, "unused-model"),
        ):
            classifier = DistilledFeatureClassifier.load(tmp_path)
            labels, confidence = classifier.predict("hello")

        assert confidence == 0.85
        assert set(labels) == set(SEMANTIC_DIMENSIONS)
        assert set(labels.values()) == {"medium"}
        assert classifier.classifier.seen_shape == (1, 3)
        assert embedding_client.embeddings.calls[0]["model"] == "text-embedding-test"

    def test_feature_model_dir_success_returns_distilled_features(
        self, tmp_path
    ) -> None:
        _write_bundle(tmp_path)
        embedding_client = _FakeEmbeddingClient([0.1, 0.2, 0.3])

        with patch(
            "kani.scorer._resolve_runtime_embedding_client",
            return_value=(embedding_client, "unused-model"),
        ):
            result = Scorer(
                feature_model_dir=tmp_path, enable_routing_log=False
            ).classify("prove this theorem")

        assert isinstance(result, ClassificationResult)
        assert result.signals["method"]["raw"] == "distilled-features"
        assert result.signals["featureVersion"] == "test-v1"
        assert set(result.signals["semanticLabels"].values()) == {"high"}
        assert len(result.dimensions) == 15
        assert result.tier == Tier.REASONING
        assert result.agentic_score == 1.0

    def test_missing_model_returns_default_fallback(self, tmp_path) -> None:
        result = Scorer(feature_model_dir=tmp_path, enable_routing_log=False).classify(
            "prove why this is complex"
        )

        assert result.tier == Tier.MEDIUM
        assert result.confidence == 0.35
        assert result.score == 0.0
        assert result.signals["method"]["raw"] == "default"
        assert result.dimensions == []

    def test_load_failure_returns_configured_default_fallback(self, tmp_path) -> None:
        (tmp_path / "feature_classifier.pkl").write_bytes(b"not a pickle")
        config = ScoringConfig(fallback_tier=Tier.COMPLEX, fallback_confidence=0.31)

        result = Scorer(
            config=config, feature_model_dir=tmp_path, enable_routing_log=False
        ).classify("anything")

        assert result.tier == Tier.COMPLEX
        assert result.confidence == 0.31
        assert result.signals["method"]["raw"] == "default"

    def test_embedding_failure_returns_default_fallback(self, tmp_path) -> None:
        _write_bundle(tmp_path)

        with patch(
            "kani.scorer._resolve_runtime_embedding_client",
            side_effect=RuntimeError("no embedding config"),
        ):
            result = Scorer(
                feature_model_dir=tmp_path, enable_routing_log=False
            ).classify("fix this bug")

        assert result.signals["method"]["raw"] == "default"
        assert result.dimensions == []

    def test_embedding_timeout_returns_default_fallback(self, tmp_path) -> None:
        _write_bundle(tmp_path)
        embedding_client = _FakeEmbeddingClient([0.1, 0.2, 0.3], delay=0.05)

        with patch(
            "kani.scorer._resolve_runtime_embedding_client",
            return_value=(embedding_client, "unused-model"),
        ):
            scorer = Scorer(feature_model_dir=tmp_path, enable_routing_log=False)
            classifier = DistilledFeatureClassifier.load(tmp_path)
            classifier.embedding_timeout_seconds = 0.001
            scorer._feature_classifier = classifier
            scorer._feature_classifier_load_attempted = True
            result = scorer.classify("hello")

        assert result.signals["method"]["raw"] == "default"
        assert result.confidence == 0.35

    def test_prediction_failure_returns_default_fallback(self, tmp_path) -> None:
        _write_bundle(tmp_path, _bundle(classifier=_FakeClassifier(fail=True)))
        embedding_client = _FakeEmbeddingClient([0.1, 0.2, 0.3])

        with patch(
            "kani.scorer._resolve_runtime_embedding_client",
            return_value=(embedding_client, "unused-model"),
        ):
            result = Scorer(
                feature_model_dir=tmp_path, enable_routing_log=False
            ).classify("hello")

        assert result.signals["method"]["raw"] == "default"
        assert result.dimensions == []

    def test_default_fallback_never_uses_heuristic_semantic_labels(
        self, tmp_path
    ) -> None:
        with patch(
            "kani.scorer._heuristic_semantic_labels",
            side_effect=AssertionError("heuristic fallback must not run"),
            create=True,
        ) as heuristic:
            result = Scorer(
                feature_model_dir=tmp_path, enable_routing_log=False
            ).classify("fix this bug and run tests")

        heuristic.assert_not_called()
        assert result.signals["method"]["raw"] == "default"
        assert "semanticLabels" not in result.signals

    def test_inspect_feature_classifier_runtime_status_reports_unloadable(
        self, tmp_path
    ) -> None:
        (tmp_path / "feature_classifier.pkl").write_bytes(b"bad")

        status = inspect_feature_classifier_runtime_status(tmp_path)

        assert status.supported is True
        assert status.exists is True
        assert status.loadable is False
        assert "unloadable" in status.message
