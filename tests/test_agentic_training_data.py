from __future__ import annotations

import json
from pathlib import Path

from kani.training_data import (
    bootstrap_agentic_dataset,
    build_agentic_dataset,
    extract_agentic_examples,
)


def test_extract_agentic_examples_supports_dict_and_list_signal_formats() -> None:
    records = [
        {
            "timestamp": "2026-03-23T10:00:00+00:00",
            "prompt": "Open the repo and update the config file with the exact target path",
            "prompt_preview": "Open the repo and update the config file",
            "tier": "SIMPLE",
            "profile": "agentic",
            "agentic_score": 1.0,
            "signals": {
                "agenticLabel": {"raw": "AGENTIC", "matches": 0},
                "agenticMethod": {"raw": "llm", "matches": 0},
            },
        },
        {
            "timestamp": "2026-03-23T10:01:00+00:00",
            "prompt_preview": "Explain the architecture",
            "tier": "SIMPLE",
            "profile": "agentic",
            "agentic_score": 0.0,
            "signals": ["agenticLabel", "agenticMethod"],
        },
        {
            "timestamp": "2026-03-23T10:02:00+00:00",
            "prompt_preview": "General chat without agentic label",
            "tier": "SIMPLE",
            "profile": "auto",
            "agentic_score": 0.0,
            "signals": ["tokenCount"],
        },
    ]

    examples = extract_agentic_examples(records)

    assert examples == [
        {
            "prompt": "Open the repo and update the config file with the exact target path",
            "label": "AGENTIC",
            "agentic_score": 1.0,
            "tier": "SIMPLE",
            "profile": "agentic",
            "timestamp": "2026-03-23T10:00:00+00:00",
        },
        {
            "prompt": "Explain the architecture",
            "label": "NON_AGENTIC",
            "agentic_score": 0.0,
            "tier": "SIMPLE",
            "profile": "agentic",
            "timestamp": "2026-03-23T10:01:00+00:00",
        },
    ]


def test_build_agentic_dataset_dedupes_by_prompt_and_keeps_latest_record(
    tmp_path: Path,
) -> None:
    log_path = tmp_path / "routing-2026-03-23.jsonl"
    lines = [
        {
            "timestamp": "2026-03-23T10:00:00+00:00",
            "prompt_preview": "Open the repo and update the config file",
            "tier": "SIMPLE",
            "profile": "agentic",
            "agentic_score": 0.0,
            "signals": ["agenticLabel", "agenticMethod"],
        },
        {
            "timestamp": "2026-03-23T10:05:00+00:00",
            "prompt_preview": "Open the repo and update the config file",
            "tier": "SIMPLE",
            "profile": "agentic",
            "agentic_score": 1.0,
            "signals": ["agenticLabel", "agenticMethod"],
        },
        {
            "timestamp": "2026-03-23T10:06:00+00:00",
            "prompt_preview": "Summarize this article",
            "tier": "SIMPLE",
            "profile": "agentic",
            "agentic_score": 0.0,
            "signals": {
                "agenticLabel": {"raw": "NON_AGENTIC", "matches": 0},
                "agenticMethod": {"raw": "llm", "matches": 0},
            },
        },
    ]
    log_path.write_text(
        "".join(json.dumps(line) + "\n" for line in lines), encoding="utf-8"
    )

    output_path = tmp_path / "agentic_training_prompts.json"
    examples = build_agentic_dataset([log_path], output_path)

    assert examples == [
        {
            "prompt": "Open the repo and update the config file",
            "label": "AGENTIC",
            "agentic_score": 1.0,
            "tier": "SIMPLE",
            "profile": "agentic",
            "timestamp": "2026-03-23T10:05:00+00:00",
        },
        {
            "prompt": "Summarize this article",
            "label": "NON_AGENTIC",
            "agentic_score": 0.0,
            "tier": "SIMPLE",
            "profile": "agentic",
            "timestamp": "2026-03-23T10:06:00+00:00",
        },
    ]

    persisted = json.loads(output_path.read_text(encoding="utf-8"))
    assert persisted == examples


class _StubAgenticClassifier:
    def __init__(self, labels: dict[str, tuple[float, str] | None]) -> None:
        self._labels = labels
        self.calls: list[str] = []

    def classify(self, text: str) -> tuple[float, str] | None:
        self.calls.append(text)
        return self._labels.get(text)


def test_bootstrap_agentic_dataset_merges_explicit_seed_override_and_classifier(
    tmp_path: Path,
) -> None:
    log_path = tmp_path / "routing-2026-03-23.jsonl"
    lines = [
        {
            "timestamp": "2026-03-23T10:00:00+00:00",
            "prompt": "Open the repo and update the config file",
            "tier": "SIMPLE",
            "profile": "agentic",
            "agentic_score": 1.0,
            "signals": {
                "agenticLabel": {"raw": "AGENTIC", "matches": 0},
                "agenticMethod": {"raw": "llm", "matches": 0},
            },
        },
        {
            "timestamp": "2026-03-23T10:01:00+00:00",
            "prompt": "Summarize this article",
            "tier": "SIMPLE",
            "profile": "agentic",
            "agentic_score": 0.0,
            "signals": {
                "agenticLabel": {"raw": "NON_AGENTIC", "matches": 0},
                "agenticMethod": {"raw": "llm", "matches": 0},
            },
        },
        {
            "timestamp": "2026-03-23T10:02:00+00:00",
            "prompt": "commit the fix",
            "tier": "SIMPLE",
            "profile": "auto",
            "signals": {},
        },
        {
            "timestamp": "2026-03-23T10:03:00+00:00",
            "prompt": "explain the architecture",
            "tier": "SIMPLE",
            "profile": "auto",
            "signals": {},
        },
        {
            "timestamp": "2026-03-23T10:04:00+00:00",
            "prompt": ".",
            "tier": "SIMPLE",
            "profile": "auto",
            "signals": {},
        },
        {
            "timestamp": "2026-03-23T10:05:00+00:00",
            "prompt": "User: compressed summary",
            "tier": "MEDIUM",
            "profile": "compress",
            "signals": {},
        },
    ]
    log_path.write_text(
        "".join(json.dumps(line) + "\n" for line in lines), encoding="utf-8"
    )

    output_path = tmp_path / "agentic_bootstrap.json"
    classifier = _StubAgenticClassifier(
        {
            "commit the fix": (1.0, "AGENTIC"),
            "explain the architecture": (0.0, "NON_AGENTIC"),
            "override me": (1.0, "AGENTIC"),
        }
    )

    examples = bootstrap_agentic_dataset(
        [log_path],
        output_path,
        classifier=classifier,
        seed_examples=[
            {"prompt": "Run the test suite and fix failures", "label": "AGENTIC"}
        ],
        label_overrides={"override me": "NON_AGENTIC"},
        excluded_prompts={"."},
        default_seed_examples=[],
        default_excluded_prompts=set(),
    )

    assert examples == [
        {
            "prompt": "Open the repo and update the config file",
            "label": "AGENTIC",
            "source": "explicit",
        },
        {
            "prompt": "Run the test suite and fix failures",
            "label": "AGENTIC",
            "source": "seed",
        },
        {
            "prompt": "Summarize this article",
            "label": "NON_AGENTIC",
            "source": "explicit",
        },
        {"prompt": "commit the fix", "label": "AGENTIC", "source": "classifier"},
        {
            "prompt": "explain the architecture",
            "label": "NON_AGENTIC",
            "source": "classifier",
        },
        {"prompt": "override me", "label": "NON_AGENTIC", "source": "override"},
    ]
    assert classifier.calls == ["commit the fix", "explain the architecture"]

    persisted = json.loads(output_path.read_text(encoding="utf-8"))
    assert persisted == examples
