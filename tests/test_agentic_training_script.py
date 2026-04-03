from __future__ import annotations

import json
import pickle
from pathlib import Path

import numpy as np
import pytest

from kani.feature_training import load_feature_examples, train_feature_classifier


def _row(agentic: str) -> dict[str, str]:
    return {
        "prompt": f"prompt-{agentic}",
        "codePresence": "low",
        "reasoningMarkers": "medium",
        "technicalTerms": "medium",
        "creativeMarkers": "low",
        "simpleIndicators": "high",
        "multiStepPatterns": "medium",
        "questionComplexity": "medium",
        "imperativeVerbs": "low",
        "constraintCount": "medium",
        "outputFormat": "low",
        "referenceComplexity": "medium",
        "negationComplexity": "low",
        "domainSpecificity": "medium",
        "agenticTask": agentic,
    }


def test_load_feature_examples_reads_semantic_dimensions(tmp_path: Path) -> None:
    data_path = tmp_path / "distilled_feature_dataset.json"
    data_path.write_text(
        json.dumps([_row("low"), _row("high")]),
        encoding="utf-8",
    )

    prompts, labels_by_dimension = load_feature_examples(data_path)

    assert prompts == ["prompt-low", "prompt-high"]
    assert labels_by_dimension["agenticTask"] == ["low", "high"]


def test_load_feature_examples_rejects_invalid_labels(tmp_path: Path) -> None:
    data_path = tmp_path / "bad_distilled_feature_dataset.json"
    bad = _row("low")
    bad["reasoningMarkers"] = "invalid"
    data_path.write_text(json.dumps([bad, _row("high")]), encoding="utf-8")

    with pytest.raises(ValueError, match="Invalid label for reasoningMarkers"):
        load_feature_examples(data_path)


def test_train_feature_classifier_writes_model_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_path = tmp_path / "distilled_feature_dataset.json"
    rows = []
    # ensure each dimension has at least two classes
    for index in range(8):
        row = {
            "prompt": f"prompt-{index}",
            "codePresence": "high" if index % 2 else "low",
            "reasoningMarkers": "high" if index % 3 == 0 else "medium",
            "technicalTerms": "high" if index % 2 else "low",
            "creativeMarkers": "medium" if index % 2 else "low",
            "simpleIndicators": "high" if index % 2 == 0 else "low",
            "multiStepPatterns": "high" if index % 2 else "low",
            "questionComplexity": "high" if index % 3 == 0 else "low",
            "imperativeVerbs": "high" if index % 2 else "low",
            "constraintCount": "high" if index % 2 else "low",
            "outputFormat": "high" if index % 2 else "low",
            "referenceComplexity": "high" if index % 2 else "low",
            "negationComplexity": "high" if index % 2 else "low",
            "domainSpecificity": "high" if index % 2 else "low",
            "agenticTask": "high" if index % 2 else "low",
        }
        rows.append(row)

    data_path.write_text(json.dumps(rows), encoding="utf-8")

    monkeypatch.setattr(
        "kani.feature_training.load_or_compute_embeddings",
        lambda client, texts, cache_path, model: np.array(
            [[float(i), float(i + 1)] for i, _ in enumerate(texts)],
            dtype=np.float32,
        ),
    )
    monkeypatch.setattr(
        "kani.feature_training.build_embedding_client",
        lambda: (object(), "test-embedding-model"),
    )

    model_path = train_feature_classifier(
        data_path=data_path,
        output_dir=tmp_path / "models",
        cache_dir=tmp_path / "cache",
    )

    assert model_path == tmp_path / "models" / "feature_classifier.pkl"
    assert model_path.exists()

    bundle = pickle.loads(model_path.read_bytes())
    assert bundle["embedding_model"] == "test-embedding-model"
    assert bundle["training_size"] == len(rows)
    assert bundle["feature_schema_version"] == "v1"
    assert "agenticTask" in bundle["label_encoders"]
    assert "weights" in bundle
