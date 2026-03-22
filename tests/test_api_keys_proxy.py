"""Tests for proxy API key authentication middleware."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from kani.api_keys import generate_key, has_keys
from kani.proxy import app, configure


@pytest.fixture(autouse=True)
def isolate_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("KANI_DATA_DIR", str(tmp_path))


@pytest.fixture
def _configured(tmp_path, monkeypatch):
    """Write a minimal config and configure the proxy."""
    config = tmp_path / "config.yaml"
    config.write_text(
        """
host: "0.0.0.0"
port: 18420
default_provider: dummy
default_profile: auto
providers:
  dummy:
    name: dummy
    base_url: "http://localhost:9999"
    api_key: "fake"
profiles:
  auto:
    tiers:
      SIMPLE:
        primary: "test-model"
        fallback: []
        provider: default
      MEDIUM:
        primary: "test-model"
        fallback: []
        provider: default
      COMPLEX:
        primary: "test-model"
        fallback: []
        provider: default
      REASONING:
        primary: "test-model"
        fallback: []
        provider: default
"""
    )
    monkeypatch.chdir(tmp_path)
    configure(str(config))


@pytest.fixture
def client(_configured):
    return TestClient(app, raise_server_exceptions=False)


class TestNoKeysConfigured:
    """When no API keys exist, all requests pass through (backward-compat)."""

    def test_health_no_auth(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_models_no_auth(self, client):
        assert not has_keys()
        resp = client.get("/v1/models")
        assert resp.status_code == 200


class TestWithKeysConfigured:
    """When API keys exist, Bearer auth is required."""

    def test_health_exempt(self, client):
        generate_key("admin")
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_models_requires_auth(self, client):
        generate_key("admin")
        resp = client.get("/v1/models")
        assert resp.status_code == 401
        assert "authentication_error" in resp.text

    def test_models_with_valid_key(self, client):
        raw = generate_key("admin")
        resp = client.get("/v1/models", headers={"Authorization": f"Bearer {raw}"})
        assert resp.status_code == 200

    def test_models_with_invalid_key(self, client):
        generate_key("admin")
        resp = client.get("/v1/models", headers={"Authorization": "Bearer bad-key"})
        assert resp.status_code == 401

    def test_chat_requires_auth(self, client):
        generate_key("admin")
        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "test-model",
                "messages": [{"role": "user", "content": "hi"}],
            },
        )
        assert resp.status_code == 401
