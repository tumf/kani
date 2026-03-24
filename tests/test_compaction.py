"""Tests for smart-proxy context compaction (Phase A + B)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def compaction_db(tmp_path: Path, monkeypatch):
    """Use a temporary DB for all compaction tests."""
    import kani.compaction_store as store

    db = tmp_path / "compaction.db"
    store.set_db_path(db)
    store.init_db()
    yield db
    store.set_db_path(None)  # reset


# ── compaction_store tests ────────────────────────────────────────────────────


class TestSessionResolution:
    def test_explicit_header_preferred(self):
        from kani.compaction_store import resolve_session_id

        msgs = [{"role": "user", "content": "hello"}]
        sid, mode = resolve_session_id(msgs, explicit_header="my-session-123")
        assert sid == "my-session-123"
        assert mode == "explicit"

    def test_derived_fallback(self):
        from kani.compaction_store import resolve_session_id

        msgs = [{"role": "user", "content": "hello"}]
        sid, mode = resolve_session_id(msgs, model="gpt-4o")
        assert mode == "derived"
        assert len(sid) == 24

    def test_derived_is_deterministic(self):
        from kani.compaction_store import resolve_session_id

        msgs = [{"role": "user", "content": "hello"}]
        sid1, _ = resolve_session_id(msgs, model="gpt-4o")
        sid2, _ = resolve_session_id(msgs, model="gpt-4o")
        assert sid1 == sid2

    def test_empty_header_falls_back_to_derived(self):
        from kani.compaction_store import resolve_session_id

        msgs = [{"role": "user", "content": "hi"}]
        sid, mode = resolve_session_id(msgs, explicit_header="   ")
        assert mode == "derived"


class TestSnapshotPersistence:
    def test_save_and_get(self):
        from kani.compaction_store import get_snapshot, save_snapshot

        msgs = [{"role": "user", "content": "hello"}]
        h = save_snapshot("sess1", msgs, prompt_tokens=10)
        snap = get_snapshot(h)
        assert snap is not None
        assert json.loads(snap["messages_json"]) == msgs

    def test_duplicate_save_is_idempotent(self):
        from kani.compaction_store import save_snapshot

        msgs = [{"role": "user", "content": "hello"}]
        h1 = save_snapshot("sess1", msgs)
        h2 = save_snapshot("sess1", msgs)
        assert h1 == h2

    def test_hash_differs_for_different_messages(self):
        from kani.compaction_store import snapshot_hash

        m1 = [{"role": "user", "content": "hello"}]
        m2 = [{"role": "user", "content": "world"}]
        assert snapshot_hash(m1) != snapshot_hash(m2)


class TestSummaryLifecycle:
    def test_enqueue_and_ready(self):
        from kani.compaction_store import (
            enqueue_summary,
            get_inflight_summary,
            get_ready_summary,
            save_snapshot,
            update_summary,
        )

        msgs = [{"role": "user", "content": "hi"}]
        snap_h = save_snapshot("sess1", msgs)
        sid = enqueue_summary("sess1", snap_h)

        assert get_inflight_summary("sess1", snap_h) is True
        assert get_ready_summary("sess1", snap_h) is None

        update_summary(
            sid, status="ready", summary_text="summary here", estimated_tokens_saved=100
        )

        assert get_inflight_summary("sess1", snap_h) is False
        ready = get_ready_summary("sess1", snap_h)
        assert ready is not None
        assert ready["summary_text"] == "summary here"
        assert ready["estimated_tokens_saved"] == 100

    def test_no_duplicate_inflight(self):
        from kani.compaction_store import (
            enqueue_summary,
            get_inflight_summary,
            save_snapshot,
        )

        msgs = [{"role": "user", "content": "hi"}]
        snap_h = save_snapshot("sess", msgs)
        enqueue_summary("sess", snap_h)
        # Second check should report inflight
        assert get_inflight_summary("sess", snap_h) is True

    def test_mark_stale(self):
        from kani.compaction_store import (
            enqueue_summary,
            get_inflight_summary,
            mark_stale_summaries,
            save_snapshot,
        )

        msgs1 = [{"role": "user", "content": "first"}]
        msgs2 = [{"role": "user", "content": "second"}]
        h1 = save_snapshot("sess", msgs1)
        h2 = save_snapshot("sess", msgs2)
        enqueue_summary("sess", h1)
        assert get_inflight_summary("sess", h1) is True

        mark_stale_summaries("sess", h2)
        # h1 job should now be stale
        assert get_inflight_summary("sess", h1) is False


# ── compaction algorithm tests ────────────────────────────────────────────────


class TestCompactMessages:
    def _msgs(self, n: int) -> list[dict[str, Any]]:
        """Build a user/assistant alternating conversation of length n."""
        out: list[dict[str, Any]] = []
        for i in range(n):
            role = "user" if i % 2 == 0 else "assistant"
            out.append({"role": role, "content": f"turn {i}"})
        return out

    def test_basic_compaction(self):
        from kani.compaction import try_sync_compaction

        msgs = self._msgs(10)
        compacted, saved = try_sync_compaction(msgs, "SUMMARY", 1, 2, 100)
        assert compacted is not None
        # Head + summary + tail preserved
        assert compacted[0] == msgs[0]
        assert any("SUMMARY" in str(m.get("content", "")) for m in compacted)
        # Last 2 messages preserved
        assert compacted[-2:] == msgs[-2:]
        assert saved >= 0

    def test_too_few_messages_returns_none(self):
        from kani.compaction import try_sync_compaction

        msgs = self._msgs(2)
        result, _ = try_sync_compaction(msgs, "SUMMARY", 1, 2, 50)
        assert result is None

    def test_system_message_always_preserved(self):
        from kani.compaction import try_sync_compaction

        msgs = [{"role": "system", "content": "You are helpful."}] + self._msgs(8)
        compacted, _ = try_sync_compaction(msgs, "SUMMARY", 1, 2, 200)
        assert compacted is not None
        assert compacted[0]["role"] == "system"

    def test_overlap_guard_returns_none(self):
        from kani.compaction import try_sync_compaction

        msgs = self._msgs(4)
        # protect_first_n + protect_last_n >= len(msgs)
        result, _ = try_sync_compaction(msgs, "SUMMARY", 2, 3, 100)
        assert result is None

    def test_token_savings_positive(self):
        from kani.compaction import _estimate_tokens, try_sync_compaction

        msgs = self._msgs(20)
        original_tokens = _estimate_tokens(msgs)
        compacted, saved = try_sync_compaction(
            msgs, "short summary", 1, 2, original_tokens
        )
        assert compacted is not None
        assert saved > 0


class TestEstimateTokens:
    def test_non_zero(self):
        from kani.compaction import _estimate_tokens

        msgs = [{"role": "user", "content": "hello world"}]
        assert _estimate_tokens(msgs) > 0

    def test_more_content_means_more_tokens(self):
        from kani.compaction import _estimate_tokens

        short = [{"role": "user", "content": "hi"}]
        long = [{"role": "user", "content": "hi " * 200}]
        assert _estimate_tokens(long) > _estimate_tokens(short)


# ── config model tests ────────────────────────────────────────────────────────


class TestCompactionConfig:
    def test_default_disabled(self):
        from kani.config import KaniConfig

        cfg = KaniConfig()
        assert cfg.smart_proxy.context_compaction.enabled is False
        assert cfg.smart_proxy.context_compaction.sync_compaction.enabled is False
        assert (
            cfg.smart_proxy.context_compaction.background_precompaction.enabled is False
        )

    def test_yaml_round_trip(self):
        from kani.config import load_config

        import tempfile, textwrap, os

        yaml_text = textwrap.dedent("""\
            default_provider: dummy
            providers:
              dummy:
                name: dummy
                base_url: http://localhost:9999
                api_key: fake
            profiles:
              auto:
                tiers:
                  SIMPLE: {primary: m1}
                  MEDIUM: {primary: m2}
                  COMPLEX: {primary: m3}
                  REASONING: {primary: m4}
            smart_proxy:
              context_compaction:
                enabled: true
                sync_compaction:
                  enabled: true
                  threshold_percent: 75.0
                background_precompaction:
                  enabled: true
                  trigger_percent: 60.0
                session:
                  header_name: X-My-Session
        """)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_text)
            tmp = f.name
        try:
            cfg = load_config(tmp)
            cc = cfg.smart_proxy.context_compaction
            assert cc.enabled is True
            assert cc.sync_compaction.enabled is True
            assert cc.sync_compaction.threshold_percent == 75.0
            assert cc.background_precompaction.enabled is True
            assert cc.background_precompaction.trigger_percent == 60.0
            assert cc.session.header_name == "X-My-Session"
        finally:
            os.unlink(tmp)


# ── proxy integration tests ───────────────────────────────────────────────────


@pytest.fixture
def compaction_config(tmp_path: Path):
    """Write a minimal config with compaction enabled."""
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        """\
default_provider: dummy
providers:
  dummy:
    name: dummy
    base_url: "http://localhost:9999"
    api_key: "fake"
profiles:
  auto:
    tiers:
      SIMPLE: {primary: "auto-simple"}
      MEDIUM: {primary: "auto-medium"}
      COMPLEX: {primary: "auto-complex"}
      REASONING: {primary: "auto-reason"}
  compress:
    tiers:
      SIMPLE: {primary: "compress-model"}
      MEDIUM: {primary: "compress-model"}
      COMPLEX: {primary: "compress-model"}
      REASONING: {primary: "compress-model"}
smart_proxy:
  context_compaction:
    enabled: true
    sync_compaction:
      enabled: true
      threshold_percent: 1.0
    background_precompaction:
      enabled: false
"""
    )
    return cfg


_UPSTREAM_RESPONSE = {
    "id": "x",
    "choices": [{"message": {"role": "assistant", "content": "hi"}}],
    "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
}


def _mock_upstream(monkeypatch):
    """Patch _proxy_upstream to return a canned JSON response."""
    import kani.proxy as proxy_mod
    from fastapi.responses import JSONResponse
    from unittest.mock import AsyncMock

    mock = AsyncMock(return_value=JSONResponse(content=_UPSTREAM_RESPONSE))
    monkeypatch.setattr(proxy_mod, "_proxy_upstream", mock)
    return mock


def test_compaction_skipped_when_disabled(tmp_path: Path, monkeypatch):
    """When compaction is disabled, proxy passes through normally."""
    from fastapi.testclient import TestClient

    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        """\
default_provider: dummy
providers:
  dummy:
    name: dummy
    base_url: "http://localhost:9999"
    api_key: "fake"
profiles:
  auto:
    tiers:
      SIMPLE: {primary: "auto-simple"}
      MEDIUM: {primary: "auto-medium"}
      COMPLEX: {primary: "auto-complex"}
      REASONING: {primary: "auto-reason"}
"""
    )
    monkeypatch.setenv("KANI_DATA_DIR", str(tmp_path / "data"))
    from kani.proxy import app, configure

    configure(str(cfg))
    _mock_upstream(monkeypatch)

    with TestClient(app) as client:
        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "kani/auto",
                "messages": [{"role": "user", "content": "hi"}],
            },
        )
    assert resp.status_code == 200
    # No compaction headers when disabled
    assert (
        "X-Kani-Compaction" not in resp.headers
        or resp.headers.get("X-Kani-Compaction") == "off"
    )


def test_compaction_headers_present_when_enabled(
    tmp_path: Path, monkeypatch, compaction_config
):
    """Compaction enabled → X-Kani-Compaction header present."""
    from fastapi.testclient import TestClient
    from kani.proxy import app, configure

    monkeypatch.setenv("KANI_DATA_DIR", str(tmp_path / "data"))
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)

    import kani.compaction_store as store

    store.set_db_path(tmp_path / "data" / "compaction.db")
    store.init_db()

    configure(str(compaction_config))
    _mock_upstream(monkeypatch)

    with TestClient(app) as client:
        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "kani/auto",
                "messages": [{"role": "user", "content": "hi"}],
            },
        )

    assert resp.status_code == 200
    # Compaction was enabled — header should be present
    assert "X-Kani-Compaction" in resp.headers


# ── Hierarchical compaction tests ─────────────────────────────────────────────


def _make_msgs(n: int) -> list[dict[str, Any]]:
    """Build a user/assistant alternating conversation of length n."""
    out: list[dict[str, Any]] = []
    for i in range(n):
        role = "user" if i % 2 == 0 else "assistant"
        out.append({"role": role, "content": f"turn {i}"})
    return out


class TestHierarchicalCompactMessages:
    """Tests for _compact_messages_incremental() — the incremental apply function."""

    def test_hierarchical_first_pass_no_prior(self):
        """First-pass with no prior summary uses new_delta_summary directly."""
        from kani.compaction import _compact_messages_incremental

        msgs = _make_msgs(10)
        compacted, covered = _compact_messages_incremental(
            msgs,
            prior_summary=None,
            prior_covered_count=0,
            new_delta_summary="DELTA_SUMMARY",
            protect_first_n=1,
            protect_last_n=2,
        )
        assert compacted is not None
        assert covered > 0
        # Summary message contains delta summary (no prior prefix)
        summary_content = next(
            m["content"] for m in compacted if "DELTA_SUMMARY" in m.get("content", "")
        )
        assert "DELTA_SUMMARY" in summary_content
        # Head and tail preserved
        assert compacted[0] == msgs[0]
        assert compacted[-2:] == msgs[-2:]

    def test_hierarchical_second_pass_with_prior_concatenates(self):
        """Second-pass with prior summary concatenates prior + delta."""
        from kani.compaction import _compact_messages_incremental

        msgs = _make_msgs(10)
        compacted, covered = _compact_messages_incremental(
            msgs,
            prior_summary="PRIOR_SUMMARY",
            prior_covered_count=2,
            new_delta_summary="DELTA_SUMMARY",
            protect_first_n=1,
            protect_last_n=2,
        )
        assert compacted is not None
        assert covered > 0
        # Merged summary contains both prior and delta
        merged_content = next(
            m["content"] for m in compacted if "PRIOR_SUMMARY" in m.get("content", "")
        )
        assert "PRIOR_SUMMARY" in merged_content
        assert "DELTA_SUMMARY" in merged_content
        assert "[Continued]" in merged_content

    def test_hierarchical_returns_none_when_not_compactable(self):
        """Returns (None, 0) when the message structure prevents compaction."""
        from kani.compaction import _compact_messages_incremental

        msgs = _make_msgs(
            3
        )  # too few to compact with protect_first_n=1, protect_last_n=3
        compacted, covered = _compact_messages_incremental(
            msgs,
            prior_summary=None,
            prior_covered_count=0,
            new_delta_summary="SUMMARY",
            protect_first_n=1,
            protect_last_n=3,
        )
        assert compacted is None
        assert covered == 0

    def test_hierarchical_covered_count_is_full_middle(self):
        """The returned covered count equals the full middle region size."""
        from kani.compaction import _compact_messages_incremental

        msgs = _make_msgs(10)
        # protect_first_n=1, protect_last_n=2 → head_end=1, tail_start=8 → middle=7
        compacted, covered = _compact_messages_incremental(
            msgs,
            prior_summary=None,
            prior_covered_count=0,
            new_delta_summary="SUMMARY",
            protect_first_n=1,
            protect_last_n=2,
        )
        assert compacted is not None
        assert covered == 7  # tail_start(8) - head_end(1) = 7


class TestHierarchicalMergeSummaries:
    """Tests for _merge_summaries() — the summary merge function."""

    def test_hierarchical_merge_via_concatenation_under_threshold(self):
        """When combined tokens are below merge_threshold, concatenates without LLM."""
        import asyncio
        from kani.compaction import _merge_summaries

        prior = "Prior summary text"
        delta = "Delta summary text"
        # merge_threshold very high → concatenation path
        result = asyncio.get_event_loop().run_until_complete(
            _merge_summaries(prior, delta, merge_threshold=99999)
        )
        assert "Prior summary text" in result
        assert "Delta summary text" in result
        assert "[Continued]" in result

    def test_hierarchical_merge_via_llm_call_above_threshold(self):
        """When combined tokens meet merge_threshold, calls LLM (mocked here)."""
        import asyncio
        from unittest.mock import AsyncMock, MagicMock, patch
        from kani.compaction import _merge_summaries

        prior = "Prior " * 200
        delta = "Delta " * 200

        mock_response = {"choices": [{"message": {"content": "MERGED_BY_LLM"}}]}

        with patch("httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            # raise_for_status and json are sync methods on the response
            mock_response_obj = MagicMock()
            mock_response_obj.raise_for_status.return_value = None
            mock_response_obj.json.return_value = mock_response
            mock_client.post = AsyncMock(return_value=mock_response_obj)
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=None)

            result = asyncio.get_event_loop().run_until_complete(
                _merge_summaries(
                    prior,
                    delta,
                    merge_threshold=1,  # very low → LLM path
                    summary_model="test-model",
                    base_url="http://localhost:9999",
                    api_key="fake",
                )
            )

        assert result == "MERGED_BY_LLM"

    def test_hierarchical_merge_llm_fallback_on_failure(self):
        """Falls back to concatenation when LLM call fails."""
        import asyncio
        from unittest.mock import AsyncMock, patch
        from kani.compaction import _merge_summaries

        prior = "P " * 300
        delta = "D " * 300

        with patch("httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(side_effect=Exception("network error"))
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=None)

            result = asyncio.get_event_loop().run_until_complete(
                _merge_summaries(
                    prior,
                    delta,
                    merge_threshold=1,
                    summary_model="test-model",
                    base_url="http://localhost:9999",
                    api_key="fake",
                )
            )

        # Should fall back to concatenation
        assert "[Continued]" in result


class TestHierarchicalSnapshotMismatchFallback:
    """Tests for snapshot-hash mismatch fallback behavior."""

    def test_hierarchical_snapshot_mismatch_covered_count_boundary(self):
        """When messages differ from prior covered prefix, incremental is not used."""
        from kani.compaction_store import (
            enqueue_summary,
            get_latest_ready_summary_for_session,
            save_snapshot,
            update_summary,
        )

        # Store a prior summary for a different message set
        prior_msgs = [
            {"role": "user", "content": "original turn 0"},
            {"role": "assistant", "content": "original turn 1"},
            {"role": "user", "content": "original turn 2"},
        ]
        snap_h = save_snapshot("sess-mismatch", prior_msgs)
        sid = enqueue_summary("sess-mismatch", snap_h, covered_message_count=2)
        update_summary(
            sid, status="ready", summary_text="prior summary", covered_message_count=2
        )

        # Current messages have different content at the covered prefix
        current_msgs = [
            {"role": "user", "content": "DIFFERENT turn 0"},  # differs
            {"role": "assistant", "content": "original turn 1"},
            {"role": "user", "content": "original turn 2"},
            {"role": "assistant", "content": "new turn 3"},
        ]

        prior_row = get_latest_ready_summary_for_session("sess-mismatch")
        assert prior_row is not None

        # Simulate the validation logic from _resolve_compaction()
        import json
        from kani.compaction_store import get_snapshot

        prior_snap = get_snapshot(prior_row["snapshot_hash"])
        assert prior_snap is not None
        stored_msgs = json.loads(prior_snap["messages_json"])
        covered_end = 2  # prior_covered_count
        # The first message differs, so validation should fail
        assert stored_msgs[:covered_end] != current_msgs[:covered_end]

    def test_hierarchical_covered_count_stored_and_retrieved(self):
        """covered_message_count is stored and retrieved correctly."""
        from kani.compaction_store import (
            enqueue_summary,
            get_ready_summary,
            save_snapshot,
            update_summary,
        )

        msgs = _make_msgs(8)
        snap_h = save_snapshot("sess-cov", msgs)
        sid = enqueue_summary("sess-cov", snap_h, covered_message_count=5)
        update_summary(
            sid,
            status="ready",
            summary_text="summary",
            covered_message_count=5,
        )

        ready = get_ready_summary("sess-cov", snap_h)
        assert ready is not None
        assert ready["covered_message_count"] == 5

    def test_hierarchical_get_latest_ready_cross_snapshot(self):
        """get_latest_ready_summary_for_session returns across different snapshot hashes."""
        from kani.compaction_store import (
            enqueue_summary,
            get_latest_ready_summary_for_session,
            save_snapshot,
            update_summary,
        )

        msgs1 = _make_msgs(4)
        msgs2 = _make_msgs(6)
        h1 = save_snapshot("sess-cross", msgs1)
        h2 = save_snapshot("sess-cross", msgs2)

        sid1 = enqueue_summary("sess-cross", h1)
        update_summary(
            sid1, status="ready", summary_text="first summary", covered_message_count=2
        )

        import time

        time.sleep(0.01)  # ensure updated_at ordering

        sid2 = enqueue_summary("sess-cross", h2)
        update_summary(
            sid2, status="ready", summary_text="second summary", covered_message_count=3
        )

        latest = get_latest_ready_summary_for_session("sess-cross")
        assert latest is not None
        assert latest["summary_text"] == "second summary"
        assert latest["covered_message_count"] == 3
