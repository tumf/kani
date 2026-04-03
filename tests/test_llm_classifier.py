"""Tests for routing logger behavior with distilled feature payloads."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from kani.logger import RoutingLogger
from kani.scorer import ClassificationResult, DimensionResult, Tier


class TestRoutingLogger:
    def test_creates_log_file_with_distilled_method(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            log_dir = Path(tmpdir) / "test_logs"
            RoutingLogger.set_log_dir(log_dir)

            result = ClassificationResult(
                score=0.42,
                tier=Tier.MEDIUM,
                confidence=0.75,
                signals={
                    "method": {"raw": "distilled-features", "matches": 0},
                    "tokenCount": 12,
                    "semanticLabels": {"agenticTask": "medium"},
                    "featureVersion": "v1",
                },
                agentic_score=0.5,
                dimensions=[
                    DimensionResult(
                        name="tokenCount",
                        raw_score=0.1,
                        weight=0.2,
                        weighted_score=0.02,
                    )
                ],
            )

            RoutingLogger.log("Hello world test prompt", result)

            assert log_dir.exists()
            log_files = list(log_dir.glob("routing-*.jsonl"))
            assert len(log_files) == 1

            with open(log_files[0], encoding="utf-8") as f:
                lines = f.readlines()
            assert len(lines) == 1

            entry = json.loads(lines[0])
            assert entry["tier"] == "MEDIUM"
            assert entry["score"] == 0.42
            assert entry["confidence"] == 0.75
            assert entry["method"] == "distilled-features"
            assert entry["signals"]["tokenCount"] == 12
            assert entry["signals"]["semanticLabels"]["agenticTask"] == "medium"
            assert entry["signals"]["featureVersion"] == "v1"
            assert entry["agentic_score"] == 0.5
            assert "timestamp" in entry

            RoutingLogger.set_log_dir(Path.home() / ".kani" / "logs")

    def test_route_log_decision_persists_signal_dict_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            log_dir = Path(tmpdir) / "test_logs"
            RoutingLogger.set_log_dir(log_dir)

            RoutingLogger.log_decision(
                "Open the repo and update config",
                tier="MEDIUM",
                score=0.55,
                confidence=0.87,
                signals={
                    "method": {"raw": "distilled-features", "matches": 0},
                    "tokenCount": 24,
                    "semanticLabels": {
                        "agenticTask": "high",
                        "multiStepPatterns": "high",
                    },
                    "featureVersion": "v1",
                },
                agentic_score=1.0,
                model="model-medium",
                provider="openrouter",
                profile="agentic",
            )

            log_files = list(log_dir.glob("routing-*.jsonl"))
            assert len(log_files) == 1
            with open(log_files[0], encoding="utf-8") as f:
                entry = json.loads(f.readline())

            assert entry["method"] == "distilled-features"
            assert entry["signals"]["tokenCount"] == 24
            assert entry["signals"]["semanticLabels"]["agenticTask"] == "high"
            assert entry["signals"]["featureVersion"] == "v1"
            assert entry["agentic_score"] == 1.0
            assert entry["model"] == "model-medium"
            assert entry["provider"] == "openrouter"
            assert entry["profile"] == "agentic"
            assert entry["classification_context"] == {}

            RoutingLogger.set_log_dir(Path.home() / ".kani" / "logs")
