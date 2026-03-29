"""Tests for proxy API key authentication middleware."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from kani.api_keys import generate_key, has_keys
from kani.proxy import _require_runtime_state, _try_with_fallbacks, app, configure
from kani.router import FallbackEntry, RoutingDecision


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
        primary: ["test-model-a", "test-model-b"]
        fallback: []
        provider: default
      MEDIUM:
        primary: "test-model"
        fallback: null
        provider: default
      COMPLEX:
        primary: "test-model"
        fallback: []
        provider: default
      REASONING:
        primary: "test-model"
        fallback: []
        provider: default
smart_proxy:
  fallback_backoff:
    enabled: true
    initial_delay_seconds: 5
    multiplier: 2
    max_delay_seconds: 60
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
        data = resp.json()
        assert "config_loaded_at" in data
        assert "config_version" in data

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
        data = resp.json()
        assert "config_loaded_at" in data
        assert "config_version" in data

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


class TestProxyFallbackBehavior:
    @pytest.mark.asyncio
    async def test_fallbacks_skip_primary_duplicate_and_dedupe(self):
        state = _require_runtime_state()
        state.fallback_backoff_state.record_success("model-primary", "primary-provider")
        state.fallback_backoff_state.record_success("model-fb-1", "fb-provider")
        state.fallback_backoff_state.record_success("model-fb-2", "fb-provider-2")

        decision = RoutingDecision(
            model="model-primary",
            provider="primary-provider",
            base_url="https://primary.example/v1",
            api_key="primary-key",
            tier="SIMPLE",
            score=0.1,
            confidence=0.9,
            profile="auto",
            fallbacks=[
                FallbackEntry(
                    model="model-primary",
                    provider="primary-provider",
                    base_url="https://primary.example/v1",
                    api_key="fb-dup-primary",
                ),
                FallbackEntry(
                    model="model-fb-1",
                    provider="fb-provider",
                    base_url="https://fb1.example/v1",
                    api_key="fb-key-1",
                ),
                FallbackEntry(
                    model="model-fb-1",
                    provider="fb-provider",
                    base_url="https://fb1-dup.example/v1",
                    api_key="fb-key-dup",
                ),
                FallbackEntry(
                    model="model-fb-2",
                    provider="fb-provider-2",
                    base_url="https://fb2.example/v1",
                    api_key="fb-key-2",
                ),
            ],
        )

        calls: list[tuple[str, str, str]] = []

        async def fake_proxy_upstream(
            base_url,
            api_key,
            body,
            _decision,
            profile=None,
            *,
            actual_provider=None,
            request_id=None,
            compaction_result=None,
        ):
            _ = profile, request_id, compaction_result
            calls.append((body["model"], actual_provider or "", base_url))
            if len(calls) < 3:
                return JSONResponse(status_code=502, content={"error": "retry"})
            return JSONResponse(status_code=200, content={"ok": True})

        with patch("kani.proxy._proxy_upstream", side_effect=fake_proxy_upstream):
            result = await _try_with_fallbacks(
                {
                    "model": decision.model,
                    "messages": [{"role": "user", "content": "hi"}],
                },
                decision,
                "auto",
            )

        assert isinstance(result, JSONResponse)
        assert result.status_code == 200
        assert calls == [
            ("model-primary", "primary-provider", "https://primary.example/v1"),
            ("model-fb-1", "fb-provider", "https://fb1.example/v1"),
            ("model-fb-2", "fb-provider-2", "https://fb2.example/v1"),
        ]

    @pytest.mark.asyncio
    async def test_fallbacks_retry_on_rate_limit(self):
        state = _require_runtime_state()
        state.fallback_backoff_state.record_success("model-primary", "primary-provider")
        state.fallback_backoff_state.record_success("model-fb-1", "fb-provider")

        decision = RoutingDecision(
            model="model-primary",
            provider="primary-provider",
            base_url="https://primary.example/v1",
            api_key="primary-key",
            tier="SIMPLE",
            score=0.1,
            confidence=0.9,
            profile="auto",
            fallbacks=[
                FallbackEntry(
                    model="model-fb-1",
                    provider="fb-provider",
                    base_url="https://fb1.example/v1",
                    api_key="fb-key-1",
                )
            ],
        )

        calls: list[tuple[str, str, str]] = []

        async def fake_proxy_upstream(
            base_url,
            api_key,
            body,
            _decision,
            profile=None,
            *,
            actual_provider=None,
            request_id=None,
            compaction_result=None,
        ):
            _ = api_key, profile, request_id, compaction_result
            calls.append((body["model"], actual_provider or "", base_url))
            if len(calls) == 1:
                return JSONResponse(status_code=429, content={"error": "rate_limited"})
            return JSONResponse(status_code=200, content={"ok": True})

        with patch("kani.proxy._proxy_upstream", side_effect=fake_proxy_upstream):
            result = await _try_with_fallbacks(
                {
                    "model": decision.model,
                    "messages": [{"role": "user", "content": "hi"}],
                },
                decision,
                "auto",
            )

        assert isinstance(result, JSONResponse)
        assert result.status_code == 200
        assert calls == [
            ("model-primary", "primary-provider", "https://primary.example/v1"),
            ("model-fb-1", "fb-provider", "https://fb1.example/v1"),
        ]

    @pytest.mark.asyncio
    async def test_skips_cooled_fallbacks_and_keeps_last_error(self):
        decision = RoutingDecision(
            model="model-primary",
            provider="primary-provider",
            base_url="https://primary.example/v1",
            api_key="primary-key",
            tier="SIMPLE",
            score=0.1,
            confidence=0.9,
            profile="auto",
            fallbacks=[
                FallbackEntry(
                    model="model-fb-1",
                    provider="fb-provider",
                    base_url="https://fb1.example/v1",
                    api_key="fb-key-1",
                ),
                FallbackEntry(
                    model="model-fb-2",
                    provider="fb-provider-2",
                    base_url="https://fb2.example/v1",
                    api_key="fb-key-2",
                ),
            ],
        )
        state = _require_runtime_state()
        state.fallback_backoff_state.record_retryable_failure(
            "model-fb-1", "fb-provider"
        )
        calls: list[tuple[str, str, str]] = []

        async def fake_proxy_upstream(
            base_url,
            api_key,
            body,
            _decision,
            profile=None,
            *,
            actual_provider=None,
            request_id=None,
            compaction_result=None,
        ):
            _ = api_key, profile, request_id, compaction_result
            calls.append((body["model"], actual_provider or "", base_url))
            return JSONResponse(status_code=502, content={"error": "retry"})

        with patch("kani.proxy._proxy_upstream", side_effect=fake_proxy_upstream):
            result = await _try_with_fallbacks(
                {
                    "model": decision.model,
                    "messages": [{"role": "user", "content": "hi"}],
                },
                decision,
                "auto",
                state=state,
            )

        assert result.status_code == 502
        assert calls == [
            ("model-primary", "primary-provider", "https://primary.example/v1"),
            ("model-fb-2", "fb-provider-2", "https://fb2.example/v1"),
        ]

    @pytest.mark.asyncio
    async def test_retryable_failure_and_success_update_backoff_state(self):
        decision = RoutingDecision(
            model="model-primary",
            provider="primary-provider",
            base_url="https://primary.example/v1",
            api_key="primary-key",
            tier="SIMPLE",
            score=0.1,
            confidence=0.9,
            profile="auto",
            fallbacks=[
                FallbackEntry(
                    model="model-fb-1",
                    provider="fb-provider",
                    base_url="https://fb1.example/v1",
                    api_key="fb-key-1",
                )
            ],
        )
        state = _require_runtime_state()
        state.fallback_backoff_state.record_success("model-primary", "primary-provider")
        state.fallback_backoff_state.record_success("model-fb-1", "fb-provider")
        call_count = 0

        async def fake_proxy_upstream(
            base_url,
            api_key,
            body,
            _decision,
            profile=None,
            *,
            actual_provider=None,
            request_id=None,
            compaction_result=None,
        ):
            nonlocal call_count
            _ = (
                base_url,
                api_key,
                profile,
                actual_provider,
                request_id,
                compaction_result,
            )
            call_count += 1
            if call_count == 1:
                return JSONResponse(status_code=502, content={"error": "retry"})
            return JSONResponse(status_code=200, content={"ok": True})

        with patch("kani.proxy._proxy_upstream", side_effect=fake_proxy_upstream):
            result = await _try_with_fallbacks(
                {
                    "model": decision.model,
                    "messages": [{"role": "user", "content": "hi"}],
                },
                decision,
                "auto",
                state=state,
            )

        assert result.status_code == 200
        assert (
            state.fallback_backoff_state.get_entry("model-primary", "primary-provider")
            is not None
        )
        assert (
            state.fallback_backoff_state.get_entry("model-fb-1", "fb-provider") is None
        )

    def test_models_list_includes_all_primary_candidates(self, client):
        resp = client.get("/v1/models")
        assert resp.status_code == 200
        ids = {item["id"] for item in resp.json()["data"]}
        assert "test-model-a" in ids
        assert "test-model-b" in ids
