from __future__ import annotations

import json
from pathlib import Path

from kani.training_data import (
    build_feature_dataset,
    deterministic_token_count,
    extract_distilled_feature_examples,
)


class _StubAnnotator:
    def __init__(self, labels: dict[str, dict[str, str] | None]) -> None:
        self._labels = labels
        self.calls: list[str] = []

    def annotate(self, prompt: str) -> dict[str, str] | None:
        self.calls.append(prompt)
        return self._labels.get(prompt)


def _labels(agentic: str = "medium") -> dict[str, str]:
    return {
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
        "agenticTask": agentic,
    }


def test_deterministic_token_count() -> None:
    assert deterministic_token_count("hello world") == 2
    assert deterministic_token_count("") == 1


def test_extract_distilled_feature_examples_prefers_log_labels_and_dedupes() -> None:
    records = [
        {
            "timestamp": "2026-03-23T10:00:00+00:00",
            "prompt": "Open the repo and update config",
            "signals": {"semanticLabels": _labels("high")},
        },
        {
            "timestamp": "2026-03-23T10:05:00+00:00",
            "prompt": "Open the repo and update config",
            "signals": {"semanticLabels": _labels("medium")},
        },
    ]

    examples = extract_distilled_feature_examples(records)

    assert len(examples) == 1
    assert examples[0]["prompt"] == "Open the repo and update config"
    assert examples[0]["agenticTask"] == "medium"
    assert examples[0]["source"] == "log"
    assert examples[0]["tokenCount"] == 6


def test_extract_distilled_feature_examples_can_annotate_missing_labels() -> None:
    records = [
        {
            "timestamp": "2026-03-23T10:00:00+00:00",
            "prompt": "Explain the architecture",
            "signals": {},
        },
    ]
    annotator = _StubAnnotator({"Explain the architecture": _labels("low")})

    examples = extract_distilled_feature_examples(records, annotator=annotator)

    assert len(examples) == 1
    assert examples[0]["source"] == "annotated"
    assert examples[0]["agenticTask"] == "low"
    assert annotator.calls == ["Explain the architecture"]


def test_build_feature_dataset_persists_examples(tmp_path: Path) -> None:
    log_path = tmp_path / "routing-2026-03-23.jsonl"
    line = {
        "timestamp": "2026-03-23T10:00:00+00:00",
        "prompt": "Summarize this article",
        "signals": {"semanticLabels": _labels("low")},
    }
    log_path.write_text(json.dumps(line) + "\n", encoding="utf-8")

    output_path = tmp_path / "distilled_feature_dataset.json"
    examples = build_feature_dataset([log_path], output_path)

    assert len(examples) == 1
    persisted = json.loads(output_path.read_text(encoding="utf-8"))
    assert persisted == examples
