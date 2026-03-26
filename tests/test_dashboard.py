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
    assert "Apply" in html
    assert "Clear" in html
    assert 'rel="icon"' in html
    assert "Latest:" in html
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


def test_log_execution_event_includes_compaction_fields(configured_dashboard, tmp_path):
    """log_execution_event writes compaction fields to JSONL and DB."""
    import json as _json

    dashboard.log_execution_event(
        request_id="req-cmp",
        tier="SIMPLE",
        score=0.2,
        confidence=0.9,
        agentic_score=0.1,
        model="m1",
        provider="p1",
        profile="auto",
        prompt_tokens=100,
        completion_tokens=20,
        total_tokens=120,
        elapsed_ms=150.0,
        compaction_mode="inline",
        compaction_tokens_saved=50,
        compaction_original_tokens=150,
        compaction_session_id="sess-abc",
    )

    # Find the written JSONL file and verify compaction fields
    from kani.dirs import log_dir

    jsonl_files = list(log_dir().glob("execution-*.jsonl"))
    assert jsonl_files, "No execution JSONL written"
    records = []
    for f in jsonl_files:
        for line in f.read_text().splitlines():
            if line.strip():
                records.append(_json.loads(line))
    assert records, "No records in JSONL"
    rec = records[-1]
    assert rec["compaction_mode"] == "inline"
    assert rec["compaction_tokens_saved"] == 50
    assert rec["compaction_original_tokens"] == 150
    assert rec["compaction_session_id"] == "sess-abc"


def test_ingest_execution_logs_maps_compaction_fields(configured_dashboard, tmp_path):
    """ingest_execution_logs maps compaction JSONL fields into DB columns."""
    import json as _json

    from kani.dirs import log_dir

    log_dir().mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    record = {
        "timestamp": now.isoformat(),
        "request_id": "req-ingest",
        "tier": "SIMPLE",
        "score": 0.2,
        "confidence": 0.9,
        "agentic_score": 0.1,
        "model": "m1",
        "provider": "p1",
        "profile": "auto",
        "prompt_tokens": 200,
        "completion_tokens": 40,
        "total_tokens": 240,
        "elapsed_ms": 100.0,
        "compaction_mode": "cached",
        "compaction_tokens_saved": 80,
        "compaction_original_tokens": 200,
        "compaction_session_id": "sess-xyz",
    }
    day_str = now.strftime("%Y-%m-%d")
    log_file = log_dir() / f"execution-{day_str}.jsonl"
    log_file.write_text(_json.dumps(record) + "\n")

    count = dashboard.ingest_execution_logs(days=1)
    assert count >= 1

    with sqlite3.connect(configured_dashboard) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT compaction_mode, compaction_tokens_saved, compaction_original_tokens, compaction_session_id FROM execution_logs WHERE request_id = 'req-ingest'"
        ).fetchone()
    assert row is not None
    assert row["compaction_mode"] == "cached"
    assert row["compaction_tokens_saved"] == 80
    assert row["compaction_original_tokens"] == 200
    assert row["compaction_session_id"] == "sess-xyz"


def test_window_summary_includes_compaction_aggregates(configured_dashboard):
    """_window_summary returns compaction_requests and compaction_tokens_saved."""
    now = datetime.now(timezone.utc)
    rows = [
        {
            "timestamp": (now - timedelta(minutes=10)).isoformat(),
            "request_id": "r1",
            "tier": "SIMPLE",
            "score": 0.2,
            "confidence": 0.9,
            "agentic_score": 0.1,
            "model": "m1",
            "provider": "p1",
            "profile": "auto",
            "prompt_tokens": 100,
            "completion_tokens": 20,
            "total_tokens": 120,
            "elapsed_ms": 100.0,
            "compaction_mode": "inline",
            "compaction_tokens_saved": 60,
            "compaction_original_tokens": 160,
            "compaction_session_id": "s1",
        },
        {
            "timestamp": (now - timedelta(minutes=9)).isoformat(),
            "request_id": "r2",
            "tier": "SIMPLE",
            "score": 0.2,
            "confidence": 0.9,
            "agentic_score": 0.1,
            "model": "m1",
            "provider": "p1",
            "profile": "auto",
            "prompt_tokens": 200,
            "completion_tokens": 40,
            "total_tokens": 240,
            "elapsed_ms": 150.0,
            "compaction_mode": "skipped",
            "compaction_tokens_saved": 0,
            "compaction_original_tokens": 200,
            "compaction_session_id": "s2",
        },
    ]
    with sqlite3.connect(configured_dashboard) as conn:
        conn.row_factory = sqlite3.Row
        for row in rows:
            dashboard._insert_execution_record(conn, row)
        conn.commit()

    with sqlite3.connect(configured_dashboard) as conn:
        conn.row_factory = sqlite3.Row
        summary = dashboard._window_summary(conn, 24)

    assert summary["compaction_requests"] == 1
    assert summary["compaction_tokens_saved"] == 60


def test_daily_trends_includes_compaction_columns(configured_dashboard):
    """_daily_trends returns compaction_requests and compaction_tokens_saved per day."""
    now = datetime.now(timezone.utc)
    rows = [
        {
            "timestamp": (now - timedelta(hours=1)).isoformat(),
            "request_id": "r3",
            "tier": "SIMPLE",
            "score": 0.2,
            "confidence": 0.9,
            "agentic_score": 0.1,
            "model": "m1",
            "provider": "p1",
            "profile": "auto",
            "prompt_tokens": 300,
            "completion_tokens": 60,
            "total_tokens": 360,
            "elapsed_ms": 200.0,
            "compaction_mode": "cached",
            "compaction_tokens_saved": 100,
            "compaction_original_tokens": 300,
            "compaction_session_id": "s3",
        },
    ]
    with sqlite3.connect(configured_dashboard) as conn:
        conn.row_factory = sqlite3.Row
        for row in rows:
            dashboard._insert_execution_record(conn, row)
        conn.commit()

    with sqlite3.connect(configured_dashboard) as conn:
        conn.row_factory = sqlite3.Row
        trends = dashboard._daily_trends(conn, days=2)

    today = now.date().isoformat()
    today_row = next((t for t in trends if t["day"] == today), None)
    assert today_row is not None
    assert today_row["compaction_requests"] >= 1
    assert today_row["compaction_tokens_saved"] >= 100


def test_render_window_cards_shows_compaction_metrics():
    """_render_window_cards includes Compacted reqs and Saved tokens rows."""
    windows = {
        "24h": {
            "routing_requests": 10,
            "execution_requests": 10,
            "prompt_tokens": 1000,
            "completion_tokens": 200,
            "total_tokens": 1200,
            "avg_elapsed_ms": 150.0,
            "usage_coverage": 1.0,
            "compaction_requests": 5,
            "compaction_tokens_saved": 300,
        },
        "7d": {
            "routing_requests": 50,
            "execution_requests": 50,
            "prompt_tokens": 5000,
            "completion_tokens": 1000,
            "total_tokens": 6000,
            "avg_elapsed_ms": 160.0,
            "usage_coverage": 1.0,
            "compaction_requests": 20,
            "compaction_tokens_saved": 1200,
        },
        "30d": {
            "routing_requests": 200,
            "execution_requests": 200,
            "prompt_tokens": 20000,
            "completion_tokens": 4000,
            "total_tokens": 24000,
            "avg_elapsed_ms": 155.0,
            "usage_coverage": 1.0,
            "compaction_requests": 80,
            "compaction_tokens_saved": 5000,
        },
    }
    html = dashboard._render_window_cards(windows)
    assert "Compacted" in html
    assert "Saved tokens" in html
    assert "5" in html  # compaction_requests for 24h


def test_render_daily_table_shows_compaction_columns():
    """_render_daily_table includes Compacted and Saved tokens columns."""
    rows = [
        {
            "day": "2026-03-24",
            "requests": 10,
            "execution_requests": 10,
            "prompt_tokens": 1000,
            "completion_tokens": 200,
            "total_tokens": 1200,
            "compaction_requests": 4,
            "compaction_tokens_saved": 250,
        }
    ]
    html = dashboard._render_daily_table(rows)
    assert "Compacted" in html
    assert "Saved tokens" in html
    assert "250" in html
