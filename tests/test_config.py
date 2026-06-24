"""Tests for kani embedding configuration."""

from __future__ import annotations

import pytest

from kani.config import EmbeddingConfig, load_config


class TestEmbeddingConfig:
    def test_embedding_defaults(self) -> None:
        cfg = EmbeddingConfig()

        assert cfg.enabled is True
        assert cfg.mode == "api"
        assert cfg.effective_mode == "api"
        assert cfg.timeout_seconds == 5.0
        assert cfg.model == "text-embedding-3-small"
        assert cfg.local_model == ""

    def test_embedding_accepts_valid_modes(self) -> None:
        assert EmbeddingConfig(mode="api").effective_mode == "api"
        assert (
            EmbeddingConfig(
                mode="local", local_model="sentence-transformers/test"
            ).effective_mode
            == "local"
        )
        assert EmbeddingConfig(mode="disabled").effective_mode == "disabled"

    def test_embedding_rejects_invalid_mode(self) -> None:
        with pytest.raises(ValueError):
            EmbeddingConfig.model_validate({"mode": "sometimes"})

    def test_embedding_rejects_invalid_timeout(self) -> None:
        with pytest.raises(ValueError):
            EmbeddingConfig(timeout_seconds=0)

    def test_embedding_legacy_enabled_false_normalizes_to_disabled(self) -> None:
        cfg = EmbeddingConfig(enabled=False)

        assert cfg.mode == "disabled"
        assert cfg.effective_mode == "disabled"

    def test_local_mode_requires_local_model(self) -> None:
        with pytest.raises(ValueError, match="local_model"):
            EmbeddingConfig(mode="local")

    def test_embedding_resolves_configured_provider(
        self, tmp_path, monkeypatch
    ) -> None:
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        config_path = tmp_path / "config.yaml"
        config_path.write_text(
            """
default_provider: openrouter
providers:
  openrouter:
    name: openrouter
    base_url: https://openrouter.ai/api/v1
    api_key: ${OPENROUTER_API_KEY}
  embeddings:
    name: embeddings
    base_url: http://127.0.0.1:8317/v1
    api_key: local-key
profiles:
  auto:
    tiers:
      SIMPLE:
        primary: model-a
embedding:
  mode: api
  provider: embeddings
  model: embed-model
  timeout_seconds: 1.25
"""
        )

        cfg = load_config(str(config_path), strict=True)

        assert cfg.embedding is not None
        assert cfg.embedding.model == "embed-model"
        assert cfg.embedding.timeout_seconds == 1.25
        assert cfg.embedding_resolved() == ("http://127.0.0.1:8317/v1", "local-key")

    def test_disabled_embedding_does_not_require_provider_resolution(
        self, tmp_path
    ) -> None:
        config_path = tmp_path / "config.yaml"
        config_path.write_text(
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
  enabled: false
  provider: missing
"""
        )

        cfg = load_config(str(config_path), strict=True)

        assert cfg.embedding is not None
        assert cfg.embedding.effective_mode == "disabled"
        assert cfg.embedding_resolved() is None
