"""Tests for kani scoring engine."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from kani.scorer import (
    AgenticClassifier,
    ClassificationResult,
    LLMClassifier,
    Scorer,
    ScoringConfig,
    Tier,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_embedding(tier: Tier, confidence: float) -> MagicMock:
    embedding = MagicMock()
    embedding.predict.return_value = (tier, confidence)
    return embedding


def _make_agentic_embedding(
    agentic_score: float,
    label: str,
    confidence: float,
) -> MagicMock:
    embedding = MagicMock()
    embedding.predict.return_value = (agentic_score, label, confidence)
    return embedding


# ---------------------------------------------------------------------------
# Model-first routing
# ---------------------------------------------------------------------------


class TestEmbeddingClassifierPath:
    def test_high_confidence_embedding_is_used(self) -> None:
        mock_llm = MagicMock(spec=LLMClassifier)
        mock_llm.classify = MagicMock(return_value=(Tier.COMPLEX, 0.8))

        with patch(
            "kani.scorer.EmbeddingClassifier.load",
            return_value=_make_embedding(Tier.SIMPLE, 0.92),
        ):
            scorer = Scorer(
                use_embedding=True,
                use_llm_classifier=True,
                llm_classifier=mock_llm,
                enable_routing_log=False,
            )
            result = scorer.classify("Hello")

        assert result.tier == Tier.SIMPLE
        assert result.confidence == 0.92
        assert result.signals["method"]["raw"] == "embedding"
        assert result.dimensions == []
        assert result.agentic_score == 0.0
        mock_llm.classify.assert_not_called()

    def test_low_confidence_embedding_escalates_to_llm(self) -> None:
        mock_llm = MagicMock(spec=LLMClassifier)
        mock_llm.classify = MagicMock(return_value=(Tier.COMPLEX, 0.8))

        with patch(
            "kani.scorer.EmbeddingClassifier.load",
            return_value=_make_embedding(Tier.SIMPLE, 0.54),
        ):
            scorer = Scorer(
                use_embedding=True,
                use_llm_classifier=True,
                llm_classifier=mock_llm,
                enable_routing_log=False,
            )
            result = scorer.classify("Build a distributed system")

        assert result.tier == Tier.COMPLEX
        assert result.confidence == 0.8
        assert result.signals["method"]["raw"] == "llm"
        assert result.signals["embeddingConfidence"]["raw"] == 0.54
        mock_llm.classify.assert_called_once()

    def test_low_confidence_embedding_returned_when_llm_disabled(self) -> None:
        with patch(
            "kani.scorer.EmbeddingClassifier.load",
            return_value=_make_embedding(Tier.MEDIUM, 0.4),
        ):
            scorer = Scorer(
                use_embedding=True,
                use_llm_classifier=False,
                enable_routing_log=False,
            )
            result = scorer.classify("Ambiguous prompt")

        assert result.tier == Tier.MEDIUM
        assert result.confidence == 0.4
        assert result.signals["method"]["raw"] == "embedding-low-confidence"


class TestAgenticClassification:
    def test_high_confidence_agentic_embedding_is_used(self) -> None:
        mock_agentic = MagicMock(spec=AgenticClassifier)

        with (
            patch(
                "kani.scorer.EmbeddingClassifier.load",
                return_value=_make_embedding(Tier.SIMPLE, 0.91),
            ),
            patch(
                "kani.scorer.AgenticEmbeddingClassifier.load",
                return_value=_make_agentic_embedding(0.93, "AGENTIC", 0.93),
            ),
        ):
            scorer = Scorer(
                agentic_classifier=mock_agentic,
                enable_routing_log=False,
            )
            result = scorer.classify(
                "Open the repo and update the config file",
                classify_agentic=True,
            )

        assert result.tier == Tier.SIMPLE
        assert result.agentic_score == 0.93
        assert result.signals["agenticMethod"]["raw"] == "embedding"
        assert result.signals["agenticLabel"]["raw"] == "AGENTIC"
        mock_agentic.classify.assert_not_called()

    def test_low_confidence_agentic_embedding_escalates_to_llm(self) -> None:
        mock_agentic = MagicMock(spec=AgenticClassifier)
        mock_agentic.classify = MagicMock(return_value=(1.0, "AGENTIC"))

        with (
            patch(
                "kani.scorer.EmbeddingClassifier.load",
                return_value=_make_embedding(Tier.SIMPLE, 0.91),
            ),
            patch(
                "kani.scorer.AgenticEmbeddingClassifier.load",
                return_value=_make_agentic_embedding(0.55, "AGENTIC", 0.55),
            ),
        ):
            scorer = Scorer(
                agentic_classifier=mock_agentic,
                enable_routing_log=False,
            )
            result = scorer.classify(
                "Open the repo and update the config file",
                classify_agentic=True,
            )

        assert result.agentic_score == 1.0
        assert result.signals["agenticMethod"]["raw"] == "llm"
        assert result.signals["agenticLabel"]["raw"] == "AGENTIC"
        assert result.signals["agenticEmbeddingConfidence"]["raw"] == 0.55
        mock_agentic.classify.assert_called_once()

    def test_low_confidence_agentic_embedding_returned_when_llm_fails(self) -> None:
        mock_agentic = MagicMock(spec=AgenticClassifier)
        mock_agentic.classify = MagicMock(return_value=None)

        with (
            patch(
                "kani.scorer.EmbeddingClassifier.load",
                return_value=_make_embedding(Tier.SIMPLE, 0.91),
            ),
            patch(
                "kani.scorer.AgenticEmbeddingClassifier.load",
                return_value=_make_agentic_embedding(0.41, "NON_AGENTIC", 0.59),
            ),
        ):
            scorer = Scorer(
                agentic_classifier=mock_agentic,
                enable_routing_log=False,
            )
            result = scorer.classify("Explain the architecture", classify_agentic=True)

        assert result.agentic_score == 0.41
        assert result.signals["agenticMethod"]["raw"] == "embedding-low-confidence"
        assert result.signals["agenticLabel"]["raw"] == "NON_AGENTIC"
        mock_agentic.classify.assert_called_once()

    def test_agentic_classifier_not_called_for_non_simple_tier(self) -> None:
        mock_agentic = MagicMock(spec=AgenticClassifier)

        with patch(
            "kani.scorer.EmbeddingClassifier.load",
            return_value=_make_embedding(Tier.COMPLEX, 0.93),
        ):
            scorer = Scorer(
                agentic_classifier=mock_agentic,
                enable_routing_log=False,
            )
            result = scorer.classify(
                "Design a distributed database", classify_agentic=True
            )

        assert result.tier == Tier.COMPLEX
        assert result.agentic_score == 0.0
        mock_agentic.classify.assert_not_called()

    def test_agentic_classifier_not_called_when_flag_disabled(self) -> None:
        mock_agentic = MagicMock(spec=AgenticClassifier)

        with patch(
            "kani.scorer.EmbeddingClassifier.load",
            return_value=_make_embedding(Tier.SIMPLE, 0.89),
        ):
            scorer = Scorer(
                agentic_classifier=mock_agentic,
                enable_routing_log=False,
            )
            result = scorer.classify("Edit the file")

        assert result.agentic_score == 0.0
        mock_agentic.classify.assert_not_called()


class TestFallbacks:
    def test_llm_used_when_embedding_model_missing(self) -> None:
        mock_llm = MagicMock(spec=LLMClassifier)
        mock_llm.classify = MagicMock(return_value=(Tier.REASONING, 0.8))

        with patch("kani.scorer.EmbeddingClassifier.load", return_value=None):
            scorer = Scorer(
                use_embedding=True,
                use_llm_classifier=True,
                llm_classifier=mock_llm,
                enable_routing_log=False,
            )
            result = scorer.classify("Prove the theorem")

        assert result.tier == Tier.REASONING
        assert result.signals["method"]["raw"] == "llm"
        mock_llm.classify.assert_called_once()

    def test_default_fallback_used_when_no_classifier_can_decide(self) -> None:
        mock_llm = MagicMock(spec=LLMClassifier)
        mock_llm.classify = MagicMock(return_value=None)

        with patch("kani.scorer.EmbeddingClassifier.load", return_value=None):
            scorer = Scorer(
                use_embedding=True,
                use_llm_classifier=True,
                llm_classifier=mock_llm,
                enable_routing_log=False,
            )
            result = scorer.classify("Something")

        assert result.tier == Tier.MEDIUM
        assert result.confidence == 0.35
        assert result.score == 0.0
        assert result.signals["method"]["raw"] == "default"

    def test_configurable_default_fallback(self) -> None:
        config = ScoringConfig(fallback_tier=Tier.COMPLEX, fallback_confidence=0.22)
        scorer = Scorer(
            config=config,
            use_embedding=False,
            use_llm_classifier=False,
            enable_routing_log=False,
        )

        result = scorer.classify("No classifier available")

        assert result.tier == Tier.COMPLEX
        assert result.confidence == 0.22
        assert result.signals["method"]["raw"] == "default"


class TestResultShape:
    def test_classification_result_shape_is_stable(self) -> None:
        with patch(
            "kani.scorer.EmbeddingClassifier.load",
            return_value=_make_embedding(Tier.SIMPLE, 0.88),
        ):
            result = Scorer(enable_routing_log=False).classify("hello")

        assert isinstance(result, ClassificationResult)
        assert isinstance(result.signals, dict)
        assert result.dimensions == []
        assert result.agentic_score == 0.0
