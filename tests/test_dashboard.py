from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from kani import dashboard
from kani.proxy import app, configure


@pytest.fixture
def configured_dashboard(tmp_path, monkeypatch):
    monkeypatch.setenv("KANI_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("KANI_LOG_DIR", str(tmp_path / "log"))
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
      SIMPLE: {primary: "auto-simple", fallback: [], provider: default}
      MEDIUM: {primary: "auto-medium", fallback: [], provider: default}
      COMPLEX: {primary: "auto-complex", fallback: [], provider: default}
      REASONING: {primary: "auto-reason", fallback: [], provider: default}
  eco:
    tiers:
      SIMPLE: {primary: "eco-simple", fallback: [], provider: default}
      MEDIUM: {primary: "eco-medium", fallback: [], provider: default}
      COMPLEX: {primary: "eco-complex", fallback: [], provider: default}
      REASONING: {primary: "eco-reason", fallback: [], provider: default}
  premium:
    tiers:
      SIMPLE: {primary: "premium-simple", fallback: [], provider: default}
      MEDIUM: {primary: "premium-medium", fallback: [], provider: default}
      COMPLEX: {primary: "premium-complex", fallback: [], provider: default}
      REASONING: {primary: "premium-reason", fallback: [], provider: default}
  compress:
    tiers:
      SIMPLE: {primary: "compress-simple", fallback: [], provider: default}
      MEDIUM: {primary: "compress-medium", fallback: [], provider: default}
      COMPLEX: {primary: "compress-complex", fallback: [], provider: default}
      REASONING: {primary: "compress-reason", fallback: [], provider: default}
"""
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(dashboard, "_DASHBOARD_DB_PATH", tmp_path / "dashboard.db")
    configure(str(config))
    dashboard._init_dashboard_db()
    return tmp_path / "dashboard.db"


@pytest.fixture
def seeded_dashboard(configured_dashboard):
    now = datetime.now(timezone.utc)
    routing_rows = [
        {
            "timestamp": (now - timedelta(minutes=5)).isoformat(),
            "tier": "SIMPLE",
            "score": 0.2,
            "confidence": 0.93,
            "agentic_score": 0.1,
            "model": "auto-simple",
            "provider": "dummy",
            "profile": "auto",
            "signals": {"length": 1},
        },
        {
            "timestamp": (now - timedelta(minutes=4)).isoformat(),
            "tier": "MEDIUM",
            "score": 0.55,
            "confidence": 0.82,
            "agentic_score": 0.4,
            "model": "eco-medium",
            "provider": "dummy",
            "profile": "eco",
            "signals": {"tools": 1},
        },
        {
            "timestamp": (now - timedelta(minutes=3)).isoformat(),
            "tier": "COMPLEX",
            "score": 0.88,
            "confidence": 0.74,
            "agentic_score": 0.8,
            "model": "premium-complex",
            "provider": "dummy",
            "profile": "premium",
            "signals": {"reasoning": 1},
        },
    ]
    execution_rows = [
        {
            "timestamp": (now - timedelta(minutes=5)).isoformat(),
            "request_id": "req-auto",
            "tier": "SIMPLE",
            "score": 0.2,
            "confidence": 0.93,
            "agentic_score": 0.1,
            "model": "auto-simple",
            "provider": "dummy",
            "profile": "auto",
            "prompt_tokens": 100,
            "completion_tokens": 20,
            "total_tokens": 120,
            "elapsed_ms": 150,
        },
        {
            "timestamp": (now - timedelta(minutes=4)).isoformat(),
            "request_id": "req-eco",
            "tier": "MEDIUM",
            "score": 0.55,
            "confidence": 0.82,
            "agentic_score": 0.4,
            "model": "eco-medium",
            "provider": "dummy",
            "profile": "eco",
            "prompt_tokens": 200,
            "completion_tokens": 50,
            "total_tokens": 250,
            "elapsed_ms": 250,
        },
        {
            "timestamp": (now - timedelta(minutes=3)).isoformat(),
            "request_id": "req-premium",
            "tier": "COMPLEX",
            "score": 0.88,
            "confidence": 0.74,
            "agentic_score": 0.8,
            "model": "premium-complex",
            "provider": "dummy",
            "profile": "premium",
            "prompt_tokens": 500,
            "completion_tokens": 120,
            "total_tokens": 620,
            "elapsed_ms": 850,
        },
    ]
    with sqlite3.connect(configured_dashboard) as conn:
        conn.row_factory = sqlite3.Row
        for row in routing_rows:
            dashboard._insert_routing_record(conn, row)
        for row in execution_rows:
            dashboard._insert_execution_record(conn, row)
        conn.commit()
    return configured_dashboard


def test_get_dashboard_stats_filters_multiple_profiles(seeded_dashboard):
    stats = dashboard.get_dashboard_stats(hours=24, profiles=["auto", "eco"])

    assert stats["selected_profiles"] == ["auto", "eco"]
    assert stats["available_profiles"] == ["auto", "compress", "eco", "premium"]
    assert stats["total_requests"] == 2
    assert stats["tier_distribution"] == {"MEDIUM": 1, "SIMPLE": 1}
    assert stats["windows"]["24h"]["total_tokens"] == 370
    assert [row["model"] for row in stats["model_usage"]["24h"]] == [
        "eco-medium",
        "auto-simple",
    ]


def test_render_dashboard_html_shows_profile_filter_controls():
    html = dashboard.render_dashboard_html(
        {
            "period_hours": 24,
            "total_requests": 2,
            "tier_distribution": {"SIMPLE": 1, "MEDIUM": 1},
            "avg_scores_by_tier": [],
            "confidence_distribution": {"90-100%": 1},
            "windows": {
                "24h": {
                    "routing_requests": 2,
                    "execution_requests": 2,
                    "prompt_tokens": 300,
                    "completion_tokens": 70,
                    "total_tokens": 370,
                    "avg_elapsed_ms": 200.0,
                    "usage_coverage": 1.0,
                },
                "7d": {
                    "routing_requests": 2,
                    "execution_requests": 2,
                    "prompt_tokens": 300,
                    "completion_tokens": 70,
                    "total_tokens": 370,
                    "avg_elapsed_ms": 200.0,
                    "usage_coverage": 1.0,
                },
                "30d": {
                    "routing_requests": 2,
                    "execution_requests": 2,
                    "prompt_tokens": 300,
                    "completion_tokens": 70,
                    "total_tokens": 370,
                    "avg_elapsed_ms": 200.0,
                    "usage_coverage": 1.0,
                },
            },
            "model_usage": {"24h": [], "7d": [], "30d": []},
            "daily_trends": [],
            "last_updated_at": None,
            "available_profiles": ["auto", "compress", "eco", "premium"],
            "selected_profiles": ["auto", "premium"],
        }
    )

    assert 'name="profiles"' in html
    assert 'value="auto" checked' in html
    assert 'value="premium" checked' in html
    assert 'value="eco"' in html
    assert "Apply filters" in html
    assert "Clear filter" in html
    assert 'rel="icon"' in html
    assert "Latest traffic <strong>" in html
    assert 'id="combined-trend-chart"' in html
    assert "renderCombinedTrendChart" in html
    assert "requests-chart" not in html
    assert "tokens-chart" not in html
    assert "input-tokens-chart" not in html
    assert "output-tokens-chart" not in html


def test_ingest_stderr_proxy_logs_enriches_legacy_routing_profile(
    configured_dashboard, tmp_path
):
    now = datetime.now(timezone.utc)
    route_ts = (now - timedelta(minutes=2)).replace(microsecond=0)
    route_iso = route_ts.isoformat()

    with sqlite3.connect(configured_dashboard) as conn:
        dashboard._insert_routing_record(
            conn,
            {
                "timestamp": route_iso,
                "tier": "SIMPLE",
                "score": 0.2,
                "confidence": 0.93,
                "agentic_score": 0.1,
                "model": None,
                "provider": None,
                "profile": None,
                "signals": {},
            },
        )
        conn.commit()

    stderr_log = tmp_path / "log" / "launchd-stderr.log"
    stderr_log.parent.mkdir(parents=True, exist_ok=True)
    local_ts = route_ts.astimezone().strftime("%Y-%m-%d %H:%M:%S,%f")
    stderr_log.write_text(
        f"{local_ts} [INFO] kani.proxy: ROUTE request_id=req1 model=auto-simple provider=dummy tier=SIMPLE score=0.2000 confidence=0.9300 agentic=0.1000 profile=auto\n",
        encoding="utf-8",
    )

    inserted = dashboard.ingest_stderr_proxy_logs()

    assert inserted == 1
    with sqlite3.connect(configured_dashboard) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT model, provider, profile FROM routing_logs WHERE timestamp = ?",
            (route_iso,),
        ).fetchone()

    assert row["model"] == "auto-simple"
    assert row["provider"] == "dummy"
    assert row["profile"] == "auto"


def test_dashboard_stats_endpoint_accepts_repeated_profile_query_params(
    seeded_dashboard,
):
    client = TestClient(app, raise_server_exceptions=False)

    response = client.get("/dashboard/stats?hours=24&profiles=auto&profiles=eco")

    assert response.status_code == 200
    payload = response.json()
    assert payload["selected_profiles"] == ["auto", "eco"]
    assert payload["total_requests"] == 2
    assert payload["windows"]["24h"]["prompt_tokens"] == 300
