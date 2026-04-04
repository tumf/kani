from __future__ import annotations

import json
from pathlib import Path

from kani.training_data import (
    LLMFeatureAnnotator,
    _classification_prompt_from_record,
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
            "classification_context": {
                "text": "[conversation]\nuser: Open the repo and update config",
                "selected_turn_count": 1,
                "selected_user_turn_count": 1,
            },
            "signals": {"semanticLabels": _labels("high")},
        },
        {
            "timestamp": "2026-03-23T10:05:00+00:00",
            "prompt": "Open the repo and update config",
            "classification_context": {
                "text": "[conversation]\nuser: Open the repo and update config",
                "selected_turn_count": 1,
                "selected_user_turn_count": 1,
            },
            "signals": {"semanticLabels": _labels("medium")},
        },
    ]

    examples = extract_distilled_feature_examples(records)

    assert len(examples) == 1
    assert (
        examples[0]["prompt"] == "[conversation]\nuser: Open the repo and update config"
    )
    assert examples[0]["agenticTask"] == "medium"
    assert examples[0]["source"] == "log"
    assert examples[0]["tokenCount"] == 8


def test_classification_prompt_from_record_prefers_context_text() -> None:
    record = {
        "prompt": "short",
        "classification_context": {"text": "[conversation]\nuser: long context"},
    }

    prompt = _classification_prompt_from_record(record)

    assert prompt == "[conversation]\nuser: long context"


def test_classification_prompt_from_record_can_rebuild_from_messages() -> None:
    record = {
        "messages": [
            {"role": "system", "content": "Use concise output"},
            {
                "role": "user",
                "content": "Create migration steps for the database",
            },
            {"role": "user", "content": "続けて"},
        ]
    }

    prompt = _classification_prompt_from_record(record)

    assert "[system]" in prompt
    assert "続けて" in prompt
    assert "Create migration steps for the database" in prompt


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


def test_llm_feature_annotator_uses_config_defaults(monkeypatch) -> None:
    class _FeatureAnnotatorConfig:
        model = "gemini-2.5-flash-lite"
        base_url = "http://127.0.0.1:8317/v1"
        api_key = "test-key"

    class _Config:
        feature_annotator = _FeatureAnnotatorConfig()

    monkeypatch.delenv("KANI_LLM_ANNOTATOR_MODEL", raising=False)
    monkeypatch.delenv("KANI_LLM_ANNOTATOR_BASE_URL", raising=False)
    monkeypatch.delenv("KANI_LLM_ANNOTATOR_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr("kani.training_data.load_config", lambda: _Config())

    annotator = LLMFeatureAnnotator()

    assert annotator.model == "gemini-2.5-flash-lite"
    assert annotator.base_url == "http://127.0.0.1:8317/v1"
    assert annotator.api_key == "test-key"


def test_checkpoint_resumes_and_skips_already_annotated(tmp_path: Path) -> None:
    checkpoint = tmp_path / "dataset.json"
    existing = [
        {
            "prompt": "Already done",
            "tokenCount": 2,
            **_labels("high"),
            "timestamp": "2026-04-01T00:00:00",
            "source": "annotated",
        }
    ]
    checkpoint.write_text(json.dumps(existing), encoding="utf-8")

    records = [
        {
            "timestamp": "2026-04-02T00:00:00",
            "prompt": "Already done",
            "signals": {},
        },
        {
            "timestamp": "2026-04-02T01:00:00",
            "prompt": "New prompt",
            "signals": {},
        },
    ]
    annotator = _StubAnnotator({"New prompt": _labels("medium")})

    examples = extract_distilled_feature_examples(
        records, annotator=annotator, checkpoint_path=checkpoint
    )

    assert len(examples) == 2
    assert annotator.calls == ["New prompt"]
