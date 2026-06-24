"""Tests for feature training embedding config."""

from __future__ import annotations

import numpy as np
import pytest

from kani.feature_training import (
    build_embedding_client,
    build_feature_classifier_bundle,
    get_embeddings,
)
from kani.scorer import LocalEmbeddingBackend


class _FakeLocalEmbeddingBackend(LocalEmbeddingBackend):
    def __init__(self, model_name: str) -> None:
        self.model_name = model_name
        self.seen: list[str] = []

    def embed(self, text: str):
        self.seen.append(text)
        return np.asarray([0.1, 0.2, 0.3], dtype=np.float32)


@pytest.mark.heavy
def test_training_local_embedding_records_configured_model_identity(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("KANI_CONFIG_DIR", str(tmp_path / "xdg_config"))
    monkeypatch.setenv("KANI_CONFIG", str(tmp_path / "config.yaml"))
    (tmp_path / "config.yaml").write_text(
        """
default_provider: openrouter
providers:
  openrouter:
    name: openrouter
    base_url: https://openrouter.ai/api/v1
profiles:
  auto:
    tiers:
      SIMPLE:
        primary: model-a
embedding:
  mode: local
  local_model: local-training-model
"""
    )
    monkeypatch.setattr(
        "kani.feature_training.LocalEmbeddingBackend", _FakeLocalEmbeddingBackend
    )

    client, model = build_embedding_client()
    embeddings = get_embeddings(client, ["a", "b"], model=model)

    bundle = build_feature_classifier_bundle(
        classifier=object(),
        label_encoders={},
        semantic_dimensions=[],
        embedding_model=model,
        embedding_dim=int(embeddings.shape[1]),
        training_size=2,
        class_distribution={},
    )

    assert model == "local-training-model"
    assert embeddings.shape == (2, 3)
    assert bundle["embedding_model"] == "local-training-model"
    assert bundle["embedding_dim"] == 3
    assert isinstance(client, _FakeLocalEmbeddingBackend)
    assert client.seen == ["a", "b"]
