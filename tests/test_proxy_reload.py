from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

import kani.proxy as proxy_mod
from kani.proxy import RuntimeState, app, configure
from kani.router import RoutingDecision


def _config_text(
    *,
    host: str = "0.0.0.0",
    port: int = 18420,
    default_profile: str = "auto",
    include_alt_profile: bool = False,
    compaction_enabled: bool = False,
    compaction_concurrency: int = 2,
) -> str:
    alt_profile = ""
    if include_alt_profile:
        alt_profile = """
  premium:
    tiers:
      SIMPLE: {primary: \"premium-simple\", fallback: [], provider: default}
      MEDIUM: {primary: \"premium-medium\", fallback: [], provider: default}
      COMPLEX: {primary: \"premium-complex\", fallback: [], provider: default}
      REASONING: {primary: \"premium-reason\", fallback: [], provider: default}
"""

    smart_proxy = """
smart_proxy:
  context_compaction:
    enabled: true
    sync_compaction:
      enabled: false
    background_precompaction:
      enabled: true
      max_concurrency: {compaction_concurrency}
""".format(compaction_concurrency=compaction_concurrency)
    if not compaction_enabled:
        smart_proxy = ""

    return f"""
host: \"{host}\"
port: {port}
default_provider: dummy
default_profile: {default_profile}
providers:
  dummy:
    name: dummy
    base_url: \"http://localhost:9999\"
    api_key: \"fake\"
profiles:
  auto:
    tiers:
      SIMPLE: {{primary: \"auto-simple\", fallback: [], provider: default}}
      MEDIUM: {{primary: \"auto-medium\", fallback: [], provider: default}}
      COMPLEX: {{primary: \"auto-complex\", fallback: [], provider: default}}
      REASONING: {{primary: \"auto-reason\", fallback: [], provider: default}}
{alt_profile}
{smart_proxy}
"""


@pytest.fixture(autouse=True)
def isolate_data_dir(tmp_path: Path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("KANI_DATA_DIR", str(data_dir))


@pytest.fixture
def config_path(tmp_path: Path) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(_config_text())
    return path


@pytest.fixture
def configured_proxy(config_path: Path):
    configure(str(config_path))
    return config_path


@pytest.fixture
def admin_token(monkeypatch):
    monkeypatch.setenv("KANI_ADMIN_TOKEN", "secret-admin-token")
    return "secret-admin-token"


def _admin_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


class TestAdminReloadAuth:
    def test_reload_rejected_without_token(self, configured_proxy):
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post("/admin/reload-config")

        assert resp.status_code == 403
        assert "admin token" in resp.text.lower()

    def test_reload_rejected_with_invalid_token(self, configured_proxy, admin_token):
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(
                "/admin/reload-config",
                headers=_admin_headers("wrong-token"),
            )

        assert resp.status_code == 403
        assert "invalid admin bearer token" in resp.text.lower()


class TestAdminReloadBehavior:
    def test_reload_success_updates_state_and_models(
        self,
        configured_proxy,
        admin_token,
        config_path: Path,
    ):
        with TestClient(app, raise_server_exceptions=False) as client:
            before_health = client.get("/health").json()
            before_models = client.get("/v1/models").json()
            before_ids = {m["id"] for m in before_models["data"]}
            assert "kani/premium" not in before_ids

            config_path.write_text(_config_text(include_alt_profile=True))
            resp = client.post(
                "/admin/reload-config",
                headers=_admin_headers(admin_token),
            )
            assert resp.status_code == 200
            payload = resp.json()
            assert payload["ok"] is True
            assert payload["reloaded"] is True
            assert payload["version"] > before_health["config_version"]

            after_models = client.get("/v1/models").json()
            after_ids = {m["id"] for m in after_models["data"]}
            assert "kani/premium" in after_ids

    def test_reload_strict_validation_failure_keeps_state(
        self,
        configured_proxy,
        admin_token,
        config_path: Path,
    ):
        with TestClient(app, raise_server_exceptions=False) as client:
            before = client.get("/health").json()

            config_path.write_text(
                """
host: "0.0.0.0"
port: 18420
default_provider: dummy
providers:
  dummy:
    name: dummy
    base_url: "http://localhost:9999"
    api_key: "fake"
"""
            )
            resp = client.post(
                "/admin/reload-config",
                headers=_admin_headers(admin_token),
            )
            assert resp.status_code == 400
            assert "Reload validation failed" in resp.text

            after = client.get("/health").json()
            assert after["config_version"] == before["config_version"]
            assert after["config_loaded_at"] == before["config_loaded_at"]

    def test_reload_rejects_non_reloadable_fields(
        self,
        configured_proxy,
        admin_token,
        config_path: Path,
    ):
        with TestClient(app, raise_server_exceptions=False) as client:
            before = client.get("/health").json()

            config_path.write_text(_config_text(host="127.0.0.1"))
            resp = client.post(
                "/admin/reload-config",
                headers=_admin_headers(admin_token),
            )
            assert resp.status_code == 409
            payload = resp.json()
            assert payload["ok"] is False
            assert "host" in payload["non_reloadable_changes"]

            after = client.get("/health").json()
            assert after["config_version"] == before["config_version"]


class TestCompactionWorkerReload:
    def test_reload_recreates_worker_on_concurrency_change(
        self,
        tmp_path: Path,
        admin_token,
    ):
        path = tmp_path / "config.yaml"
        path.write_text(_config_text(compaction_enabled=True, compaction_concurrency=1))
        configure(str(path))

        with TestClient(app, raise_server_exceptions=False) as client:
            before_worker = proxy_mod.get_worker()
            assert before_worker is not None
            before_limit = before_worker._semaphore._value

            path.write_text(
                _config_text(compaction_enabled=True, compaction_concurrency=3)
            )
            resp = client.post(
                "/admin/reload-config",
                headers=_admin_headers(admin_token),
            )
            assert resp.status_code == 200

            after_worker = proxy_mod.get_worker()
            assert after_worker is not None
            assert after_worker._semaphore._value != before_limit

    def test_reload_disable_compaction_stops_worker(
        self,
        tmp_path: Path,
        admin_token,
    ):
        path = tmp_path / "config.yaml"
        path.write_text(_config_text(compaction_enabled=True, compaction_concurrency=2))
        configure(str(path))

        with TestClient(app, raise_server_exceptions=False) as client:
            assert proxy_mod.get_worker() is not None

            path.write_text(_config_text(compaction_enabled=False))
            resp = client.post(
                "/admin/reload-config",
                headers=_admin_headers(admin_token),
            )
            assert resp.status_code == 200
            assert proxy_mod.get_worker() is None


class TestInFlightSnapshotBehavior:
    def test_routed_request_keeps_start_of_request_state(self, configured_proxy):
        old_state = proxy_mod._require_runtime_state()

        old_decision = RoutingDecision(
            model="old-model",
            provider="dummy",
            base_url="http://localhost:9999",
            api_key="fake",
            profile="auto",
            tier="SIMPLE",
            score=0.1,
            confidence=0.9,
        )
        new_decision = RoutingDecision(
            model="new-model",
            provider="dummy",
            base_url="http://localhost:9999",
            api_key="fake",
            profile="auto",
            tier="SIMPLE",
            score=0.8,
            confidence=0.95,
        )

        old_router = MagicMock()
        old_router.route.return_value = old_decision
        new_router = MagicMock()
        new_router.route.return_value = new_decision

        proxy_mod._activate_state(
            RuntimeState(
                config_path=old_state.config_path,
                config=old_state.config,
                router=old_router,
                config_loaded_at=old_state.config_loaded_at,
                version=old_state.version,
            )
        )

        fallback_response = JSONResponse(content={"ok": True})
        try:

            async def fake_resolve_compaction(
                messages: list[dict[str, Any]],
                request,
                profile,
                request_id,
                model,
                *,
                state,
            ):
                proxy_mod._activate_state(
                    RuntimeState(
                        config_path=old_state.config_path,
                        config=old_state.config,
                        router=new_router,
                        config_loaded_at=old_state.config_loaded_at,
                        version=old_state.version + 1,
                    )
                )
                from kani.compaction import CompactionResult

                return CompactionResult(mode="off", messages=messages)

            with pytest.MonkeyPatch.context() as mp:
                mp.setattr(proxy_mod, "_resolve_compaction", fake_resolve_compaction)
                try_with_fallbacks = AsyncMock(return_value=fallback_response)
                mp.setattr(proxy_mod, "_try_with_fallbacks", try_with_fallbacks)

                with TestClient(app, raise_server_exceptions=False) as client:
                    resp = client.post(
                        "/v1/chat/completions",
                        json={
                            "model": "kani/auto",
                            "messages": [{"role": "user", "content": "hello"}],
                        },
                    )

                assert resp.status_code == 200
                assert try_with_fallbacks.await_count == 1
                called_decision = try_with_fallbacks.await_args_list[0].args[1]
                assert called_decision.model == "old-model"

        finally:
            proxy_mod._activate_state(old_state)
