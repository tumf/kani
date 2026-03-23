"""Tests for LLM classifier escalation and routing logger."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from kani.logger import RoutingLogger
from kani.scorer import (
    AgenticClassifier,
    ClassificationResult,
    LLMClassifier,
    Scorer,
    Tier,
)


# ---------------------------------------------------------------------------
# Model-first scorer / LLM escalation
# ---------------------------------------------------------------------------


class TestLLMClassifierUsage:
    def test_high_confidence_embedding_skips_llm(self) -> None:
        """When embedding confidence is high enough, LLM should NOT be called."""
        mock_llm = MagicMock(spec=LLMClassifier)
        mock_llm.classify = MagicMock(return_value=(Tier.COMPLEX, 0.8))

        embedding = MagicMock()
        embedding.predict.return_value = (Tier.SIMPLE, 0.91)

        with patch("kani.scorer.EmbeddingClassifier.load", return_value=embedding):
            scorer = Scorer(
                use_embedding=True,
                use_llm_classifier=True,
                llm_classifier=mock_llm,
                enable_routing_log=False,
            )
            result = scorer.classify("Hello")

        assert result.tier == Tier.SIMPLE
        assert result.signals["method"]["raw"] == "embedding"
        mock_llm.classify.assert_not_called()

    def test_low_confidence_embedding_calls_llm(self) -> None:
        """When embedding confidence is low, LLM classifier should be called."""
        mock_llm = MagicMock(spec=LLMClassifier)
        mock_llm.classify = MagicMock(return_value=(Tier.COMPLEX, 0.8))

        embedding = MagicMock()
        embedding.predict.return_value = (Tier.MEDIUM, 0.41)

        with patch("kani.scorer.EmbeddingClassifier.load", return_value=embedding):
            scorer = Scorer(
                use_embedding=True,
                use_llm_classifier=True,
                llm_classifier=mock_llm,
                enable_routing_log=False,
            )
            result = scorer.classify("Build a system")

        mock_llm.classify.assert_called_once()
        assert result.tier == Tier.COMPLEX
        assert result.confidence == 0.8
        assert result.signals["method"]["raw"] == "llm"
        assert result.signals["embeddingConfidence"]["raw"] == 0.41

    def test_llm_failure_falls_back_to_low_confidence_embedding(self) -> None:
        """If LLM fails, keep the embedding prediction instead of using rules."""
        mock_llm = MagicMock(spec=LLMClassifier)
        mock_llm.classify = MagicMock(return_value=None)

        embedding = MagicMock()
        embedding.predict.return_value = (Tier.COMPLEX, 0.49)

        with patch("kani.scorer.EmbeddingClassifier.load", return_value=embedding):
            scorer = Scorer(
                use_embedding=True,
                use_llm_classifier=True,
                llm_classifier=mock_llm,
                enable_routing_log=False,
            )
            result = scorer.classify("Ambiguous prompt")

        mock_llm.classify.assert_called_once()
        assert result.tier == Tier.COMPLEX
        assert result.confidence == 0.49
        assert result.signals["method"]["raw"] == "embedding-low-confidence"

    def test_llm_disabled_skips_call(self) -> None:
        """When use_llm_classifier=False, LLM should never be called."""
        mock_llm = MagicMock(spec=LLMClassifier)
        embedding = MagicMock()
        embedding.predict.return_value = (Tier.MEDIUM, 0.45)

        with patch("kani.scorer.EmbeddingClassifier.load", return_value=embedding):
            scorer = Scorer(
                use_embedding=True,
                use_llm_classifier=False,
                llm_classifier=mock_llm,
                enable_routing_log=False,
            )
            scorer.classify("What is quantum computing?")

        mock_llm.classify.assert_not_called()


# ---------------------------------------------------------------------------
# LLMClassifier unit tests
# ---------------------------------------------------------------------------


class TestLLMClassifierUnit:
    def test_successful_classification(self) -> None:
        """LLMClassifier parses a valid response correctly."""
        clf = LLMClassifier(
            model="test-model",
            base_url="http://localhost:9999",
            api_key="***",
        )

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "COMPLEX"}}]
        }

        with patch("kani.scorer.httpx.post", return_value=mock_response) as mock_post:
            result = clf.classify("some prompt")

        assert result is not None
        tier, confidence = result
        assert tier == Tier.COMPLEX
        assert confidence == 0.8
        mock_post.assert_called_once()

    def test_timeout_returns_none(self) -> None:
        """LLMClassifier returns None on timeout."""
        clf = LLMClassifier(
            model="test-model",
            base_url="http://localhost:9999",
            api_key="***",
        )

        with patch("kani.scorer.httpx.post", side_effect=Exception("timeout")):
            result = clf.classify("some prompt")

        assert result is None

    def test_invalid_response_returns_none(self) -> None:
        """LLMClassifier returns None when LLM returns garbage."""
        clf = LLMClassifier(
            model="test-model",
            base_url="http://localhost:9999",
            api_key="***",
        )

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "I think it's complicated"}}]
        }

        with patch("kani.scorer.httpx.post", return_value=mock_response):
            result = clf.classify("some prompt")

        assert result is None

    def test_prompt_truncation(self) -> None:
        """LLMClassifier truncates text to 500 chars in prompt."""
        clf = LLMClassifier(
            model="test-model",
            base_url="http://localhost:9999",
            api_key="***",
        )

        long_text = "x" * 1000

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "SIMPLE"}}]
        }

        with patch("kani.scorer.httpx.post", return_value=mock_response) as mock_post:
            clf.classify(long_text)

        call_args = mock_post.call_args
        messages = call_args.kwargs.get("json", call_args[1].get("json", {}))[
            "messages"
        ]
        user_content = messages[0]["content"]
        assert "x" * 500 in user_content
        assert "x" * 501 not in user_content


class TestAgenticClassifierUnit:
    def test_agentic_label_maps_to_one(self) -> None:
        clf = AgenticClassifier(
            model="test-model",
            base_url="http://localhost:9999",
            api_key="***",
        )

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "AGENTIC"}}]
        }

        with patch("kani.scorer.httpx.post", return_value=mock_response):
            result = clf.classify("edit the file and run tests")

        assert result == (1.0, "AGENTIC")

    def test_non_agentic_label_maps_to_zero(self) -> None:
        clf = AgenticClassifier(
            model="test-model",
            base_url="http://localhost:9999",
            api_key="***",
        )

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "NON_AGENTIC"}}]
        }

        with patch("kani.scorer.httpx.post", return_value=mock_response):
            result = clf.classify("explain the architecture")

        assert result == (0.0, "NON_AGENTIC")


# ---------------------------------------------------------------------------
# RoutingLogger tests
# ---------------------------------------------------------------------------


class TestRoutingLogger:
    def test_creates_log_file(self) -> None:
        """RoutingLogger creates the log directory and file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_dir = Path(tmpdir) / "test_logs"
            RoutingLogger.set_log_dir(log_dir)

            result = ClassificationResult(
                score=0.42,
                tier=Tier.MEDIUM,
                confidence=0.75,
                signals={"method": {"raw": "default", "matches": 0}},
                agentic_score=0.1,
                dimensions=[],
            )

            RoutingLogger.log("Hello world test prompt", result)

            assert log_dir.exists()
            log_files = list(log_dir.glob("routing-*.jsonl"))
            assert len(log_files) == 1

            with open(log_files[0]) as f:
                lines = f.readlines()
            assert len(lines) == 1

            entry = json.loads(lines[0])
            assert entry["tier"] == "MEDIUM"
            assert entry["score"] == 0.42
            assert entry["confidence"] == 0.75
            assert entry["method"] == "default"
            assert entry["prompt"] == "Hello world test prompt"
            assert entry["prompt_preview"] == "Hello world test prompt"
            assert entry["agentic_score"] == 0.1
            assert "timestamp" in entry

            RoutingLogger.set_log_dir(Path.home() / ".kani" / "logs")

    def test_multiple_logs_append(self) -> None:
        """Multiple log calls append to the same file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_dir = Path(tmpdir) / "test_logs"
            RoutingLogger.set_log_dir(log_dir)

            result = ClassificationResult(
                score=0.5,
                tier=Tier.COMPLEX,
                confidence=0.9,
                signals={"method": {"raw": "llm", "matches": 0}},
                agentic_score=0.0,
                dimensions=[],
            )

            RoutingLogger.log("First prompt", result)
            RoutingLogger.log("Second prompt", result)

            log_files = list(log_dir.glob("routing-*.jsonl"))
            assert len(log_files) == 1

            with open(log_files[0]) as f:
                lines = f.readlines()
            assert len(lines) == 2

            entry1 = json.loads(lines[0])
            entry2 = json.loads(lines[1])
            assert entry1["prompt_preview"] == "First prompt"
            assert entry2["prompt_preview"] == "Second prompt"

            RoutingLogger.set_log_dir(Path.home() / ".kani" / "logs")

    def test_prompt_preview_truncated(self) -> None:
        """Prompt preview is truncated to 200 chars."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_dir = Path(tmpdir) / "test_logs"
            RoutingLogger.set_log_dir(log_dir)

            long_prompt = "a" * 500
            result = ClassificationResult(
                score=0.1,
                tier=Tier.SIMPLE,
                confidence=0.95,
                signals={"method": {"raw": "embedding", "matches": 0}},
                agentic_score=0.0,
                dimensions=[],
            )

            RoutingLogger.log(long_prompt, result)

            log_files = list(log_dir.glob("routing-*.jsonl"))
            with open(log_files[0]) as f:
                entry = json.loads(f.readline())

            assert entry["prompt"] == long_prompt
            assert len(entry["prompt_preview"]) == 200

            RoutingLogger.set_log_dir(Path.home() / ".kani" / "logs")
