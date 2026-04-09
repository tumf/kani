"""Tests for kani distilled feature scoring engine."""

from __future__ import annotations

from unittest.mock import patch

from kani.config import KaniConfig
from kani.scorer import (
    ClassificationResult,
    Scorer,
    ScoringConfig,
    Tier,
    _build_embedding_client,
)


class _StubFeatureClassifier:
    def __init__(self) -> None:
        self.weights = {
            "tokenCount": 0.2,
            "codePresence": 1.0,
            "reasoningMarkers": 1.3,
            "technicalTerms": 1.0,
            "creativeMarkers": 0.8,
            "simpleIndicators": 1.0,
            "multiStepPatterns": 1.2,
            "questionComplexity": 1.1,
            "imperativeVerbs": 0.9,
            "constraintCount": 1.0,
            "outputFormat": 0.8,
            "referenceComplexity": 0.9,
            "negationComplexity": 0.9,
            "domainSpecificity": 1.0,
            "agenticTask": 1.4,
        }
        self.tier_thresholds = {"SIMPLE": 0.2, "MEDIUM": 0.45, "COMPLEX": 0.7}

    def predict(self, text: str) -> tuple[dict[str, str], float]:
        if "prove" in text.lower():
            return (
                {
                    "codePresence": "medium",
                    "reasoningMarkers": "high",
                    "technicalTerms": "high",
                    "creativeMarkers": "low",
                    "simpleIndicators": "low",
                    "multiStepPatterns": "high",
                    "questionComplexity": "high",
                    "imperativeVerbs": "medium",
                    "constraintCount": "high",
                    "outputFormat": "medium",
                    "referenceComplexity": "high",
                    "negationComplexity": "medium",
                    "domainSpecificity": "high",
                    "agenticTask": "high",
                },
                0.88,
            )

        return (
            {
                "codePresence": "low",
                "reasoningMarkers": "low",
                "technicalTerms": "low",
                "creativeMarkers": "low",
                "simpleIndicators": "high",
                "multiStepPatterns": "low",
                "questionComplexity": "low",
                "imperativeVerbs": "low",
                "constraintCount": "low",
                "outputFormat": "low",
                "referenceComplexity": "low",
                "negationComplexity": "low",
                "domainSpecificity": "low",
                "agenticTask": "medium",
            },
            0.81,
        )


class TestEmbeddingClientConfig:
    def test_embedding_provider_resolves_via_provider_map(self) -> None:
        config = KaniConfig.model_validate(
            {
                "default_provider": "cliproxy",
                "providers": {
                    "cliproxy": {
                        "name": "cliproxy",
                        "base_url": "http://example.invalid/v1",
                        "api_key": "secret",
                    }
                },
                "embedding": {
                    "provider": "cliproxy",
                    "model": "text-embedding-test",
                },
            }
        )

        with patch("kani.config.load_config", return_value=config):
            client, model = _build_embedding_client("fallback-model")

        assert str(client.base_url) == "http://example.invalid/v1/"
        assert model == "text-embedding-test"

    def test_embedding_base_url_still_takes_precedence(self) -> None:
        config = KaniConfig.model_validate(
            {
                "default_provider": "cliproxy",
                "providers": {
                    "cliproxy": {
                        "name": "cliproxy",
                        "base_url": "http://provider.invalid/v1",
                        "api_key": "secret",
                    }
                },
                "embedding": {
                    "provider": "cliproxy",
                    "base_url": "http://direct.invalid/v1",
                    "api_key": "direct-key",
                    "model": "text-embedding-direct",
                },
            }
        )

        with patch("kani.config.load_config", return_value=config):
            client, model = _build_embedding_client("fallback-model")

        assert str(client.base_url) == "http://direct.invalid/v1/"
        assert model == "text-embedding-direct"


class TestDistilledFeatureScorer:
    def test_feature_model_path_returns_distilled_method_and_dimensions(self) -> None:
        with patch(
            "kani.scorer.DistilledFeatureClassifier.load",
            return_value=_StubFeatureClassifier(),
        ):
            result = Scorer(enable_routing_log=False).classify("hello world")

        assert isinstance(result, ClassificationResult)
        assert result.signals["method"]["raw"] == "distilled-features"
        assert result.signals["featureVersion"] == "v1"
        assert isinstance(result.signals["semanticLabels"], dict)
        assert result.agentic_score == 0.5
        assert len(result.dimensions) == 15
        assert result.tier in {Tier.SIMPLE, Tier.MEDIUM, Tier.COMPLEX, Tier.REASONING}

    def test_agentic_score_is_derived_from_agentic_task_dimension(self) -> None:
        with patch(
            "kani.scorer.DistilledFeatureClassifier.load",
            return_value=_StubFeatureClassifier(),
        ):
            result = Scorer(enable_routing_log=False).classify("prove this theorem")

        assert result.agentic_score == 1.0
        assert result.tier in {Tier.COMPLEX, Tier.REASONING}

    def test_default_fallback_when_feature_model_missing(self) -> None:
        config = ScoringConfig(fallback_tier=Tier.MEDIUM, fallback_confidence=0.31)
        with patch("kani.scorer.DistilledFeatureClassifier.load", return_value=None):
            result = Scorer(config=config, enable_routing_log=False).classify(
                "anything"
            )

        assert result.tier == Tier.MEDIUM
        assert result.confidence == 0.31
        assert result.score == 0.0
        assert result.signals["method"]["raw"] == "default"
        assert result.agentic_score == 0.0
        assert result.dimensions == []
