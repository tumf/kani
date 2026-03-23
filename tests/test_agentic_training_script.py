from __future__ import annotations

import json
import pickle
from pathlib import Path

import numpy as np
import pytest

from kani.agentic_training import load_agentic_examples, train_agentic_classifier


def test_load_agentic_examples_reads_prompt_and_label_fields(tmp_path: Path) -> None:
    data_path = tmp_path / "agentic_training_prompts.json"
    data_path.write_text(
        json.dumps(
            [
                {"prompt": "Open the repo and update the config", "label": "AGENTIC"},
                {"prompt": "Explain the architecture", "label": "NON_AGENTIC"},
            ]
        ),
        encoding="utf-8",
    )

    prompts, labels = load_agentic_examples(data_path)

    assert prompts == [
        "Open the repo and update the config",
        "Explain the architecture",
    ]
    assert labels == ["AGENTIC", "NON_AGENTIC"]


def test_load_agentic_examples_rejects_unknown_labels(tmp_path: Path) -> None:
    data_path = tmp_path / "bad_agentic_training_prompts.json"
    data_path.write_text(
        json.dumps([{"prompt": "hello", "label": "MAYBE"}]),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Unsupported agentic labels"):
        load_agentic_examples(data_path)


def test_train_agentic_classifier_writes_model_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_path = tmp_path / "agentic_training_prompts.json"
    data_path.write_text(
        json.dumps(
            [
                {"prompt": "Open the repo and update the config", "label": "AGENTIC"},
                {"prompt": "Run the test suite and fix failures", "label": "AGENTIC"},
                {"prompt": "Explain what Kubernetes is", "label": "NON_AGENTIC"},
                {"prompt": "Summarize this article", "label": "NON_AGENTIC"},
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "kani.agentic_training.load_or_compute_embeddings",
        lambda client, texts, cache_path, model: np.array(
            [
                [1.0, 0.0],
                [0.9, 0.1],
                [0.0, 1.0],
                [0.1, 0.9],
            ],
            dtype=np.float32,
        ),
    )
    monkeypatch.setattr(
        "kani.agentic_training.get_embeddings",
        lambda client, texts, model: np.array(
            [[0.8, 0.2], [0.2, 0.8]],
            dtype=np.float32,
        ),
    )
    monkeypatch.setattr(
        "kani.agentic_training.build_embedding_client",
        lambda: (object(), "test-embedding-model"),
    )

    model_path = train_agentic_classifier(
        data_path=data_path,
        output_dir=tmp_path / "models",
        cache_dir=tmp_path / "cache",
    )

    assert model_path == tmp_path / "models" / "agentic_classifier.pkl"
    assert model_path.exists()

    bundle = pickle.loads(model_path.read_bytes())
    assert bundle["embedding_model"] == "test-embedding-model"
    assert bundle["training_size"] == 4
    assert bundle["label_type"] == "agentic"
    assert bundle["class_distribution"] == {"AGENTIC": 2, "NON_AGENTIC": 2}
    assert list(bundle["label_encoder"].classes_) == ["AGENTIC", "NON_AGENTIC"]
