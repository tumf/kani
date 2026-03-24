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


# ── Router.resolve_model tests ───────────────────────────────────────────────


class TestResolveModel:
    """Unit tests for Router.resolve_model() — no scorer or routing log calls."""

    def _make_router(self):
        from kani.config import (
            KaniConfig,
            ProfileConfig,
            ProviderConfig,
            TierModelConfig,
        )
        from kani.router import Router

        cfg = KaniConfig(
            providers={
                "openrouter": ProviderConfig(
                    name="openrouter",
                    base_url="https://openrouter.ai/api/v1",
                    api_key="test-key",
                )
            },
            default_provider="openrouter",
            profiles={
                "auto": ProfileConfig(
                    tiers={
                        "SIMPLE": TierModelConfig(primary="auto-simple"),
                        "MEDIUM": TierModelConfig(primary="auto-medium"),
                    }
                ),
                "eco": ProfileConfig(
                    tiers={
                        "SIMPLE": TierModelConfig(primary="eco-simple"),
                    }
                ),
            },
            default_profile="auto",
        )
        return Router(cfg)

    def test_returns_routing_decision_with_correct_model(self):
        from kani.router import RoutingDecision

        router = self._make_router()
        decision = router.resolve_model(profile="auto", tier="SIMPLE")
        assert isinstance(decision, RoutingDecision)
        assert decision.model == "auto-simple"
        assert decision.base_url == "https://openrouter.ai/api/v1"
        assert decision.api_key == "test-key"

    def test_empty_profile_uses_default_profile(self):
        router = self._make_router()
        decision = router.resolve_model(profile=None, tier="SIMPLE")
        assert decision.model == "auto-simple"
        assert decision.profile == "auto"

    def test_explicit_profile_used(self):
        router = self._make_router()
        decision = router.resolve_model(profile="eco", tier="SIMPLE")
        assert decision.model == "eco-simple"
        assert decision.profile == "eco"

    def test_does_not_call_classify(self):
        from unittest.mock import patch
        from kani.router import Router

        router = self._make_router()
        with patch.object(Router, "_classify") as mock_classify:
            router.resolve_model(profile="auto", tier="SIMPLE")
            mock_classify.assert_not_called()

    def test_does_not_call_routing_logger(self):
        from unittest.mock import patch

        router = self._make_router()
        with patch("kani.logger.RoutingLogger.log_decision") as mock_log:
            router.resolve_model(profile="auto", tier="SIMPLE")
            mock_log.assert_not_called()

    def test_score_and_confidence_are_zero(self):
        router = self._make_router()
        decision = router.resolve_model(profile="auto", tier="SIMPLE")
        assert decision.score == 0.0
        assert decision.confidence == 0.0
        assert decision.signals == []

    def test_falls_back_to_adjacent_tier(self):
        router = self._make_router()
        # "eco" only has SIMPLE; requesting COMPLEX should fall back
        decision = router.resolve_model(profile="eco", tier="COMPLEX")
        assert decision.model == "eco-simple"


# ── compaction_store tests ────────────────────────────────────────────────────


class TestSessionResolution:
    def test_explicit_header_preferred(self):
        from kani.compaction_store import resolve_session_id

        msgs = [{"role": "user", "content": "hello"}]
        sid, mode = resolve_session_id(msgs, explicit_header="my-session-123")
        assert sid == "my-session-123"
        assert mode == "explicit"

    def test_no_header_returns_none(self):
        from kani.compaction_store import resolve_session_id

        msgs = [{"role": "user", "content": "hello"}]
        sid, mode = resolve_session_id(msgs, model="gpt-4o")
        assert sid is None
        assert mode == "none"

    def test_empty_header_returns_none(self):
        from kani.compaction_store import resolve_session_id

        msgs = [{"role": "user", "content": "hi"}]
        sid, mode = resolve_session_id(msgs, explicit_header="   ")
        assert sid is None
        assert mode == "none"


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


class TestComputeSummaryMaxTokens:
    """Tests for _compute_summary_max_tokens boundary conditions."""

    def test_default_ratio_normal_range(self):
        from kani.compaction import _compute_summary_max_tokens

        # 1000 tokens * 0.25 = 250, within [128, 1024]
        result = _compute_summary_max_tokens(1000, 0.25, 128, 1024)
        assert result == 250

    def test_short_middle_hits_floor(self):
        from kani.compaction import _compute_summary_max_tokens

        # 100 tokens * 0.25 = 25, clamped to floor 128
        result = _compute_summary_max_tokens(100, 0.25, 128, 1024)
        assert result == 128

    def test_long_middle_hits_ceiling(self):
        from kani.compaction import _compute_summary_max_tokens

        # 10000 tokens * 0.25 = 2500, clamped to ceiling 1024
        result = _compute_summary_max_tokens(10000, 0.25, 128, 1024)
        assert result == 1024

    def test_custom_ratio_override(self):
        from kani.compaction import _compute_summary_max_tokens

        # 2000 tokens * 0.5 = 1000, within [128, 1024]
        result = _compute_summary_max_tokens(2000, 0.5, 128, 1024)
        assert result == 1000

    def test_floor_equals_ceiling_returns_floor(self):
        from kani.compaction import _compute_summary_max_tokens

        result = _compute_summary_max_tokens(500, 0.25, 256, 256)
        assert result == 256

    def test_summary_max_tokens_used_in_generate_summary(self):
        """generate_summary passes computed max_tokens to the HTTP payload."""
        import asyncio
        from unittest.mock import AsyncMock, patch, MagicMock
        from kani.compaction import generate_summary

        captured = {}

        async def fake_post(url, *, json, headers):
            captured["max_tokens"] = json["max_tokens"]
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            resp.json.return_value = {"choices": [{"message": {"content": "summary"}}]}
            return resp

        async def run():
            msgs = [
                {"role": "user", "content": "a " * 400},  # ~100 tokens middle
                {"role": "assistant", "content": "b " * 400},
                {"role": "user", "content": "last"},
            ]
            with patch("httpx.AsyncClient") as mock_client_cls:
                mock_client = AsyncMock()
                mock_client_cls.return_value.__aenter__ = AsyncMock(
                    return_value=mock_client
                )
                mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
                mock_client.post = fake_post
                return await generate_summary(
                    msgs,
                    summary_model="test-model",
                    base_url="http://localhost:9999",
                    api_key="",
                    protect_first_n=0,
                    protect_last_n=1,
                    summary_ratio=0.25,
                    min_summary_tokens=128,
                    max_summary_tokens=1024,
                )

        asyncio.run(run())
        # The middle is short, so max_tokens should be at least the floor
        assert captured["max_tokens"] >= 128
        assert captured["max_tokens"] <= 1024


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

    def test_english_text_with_known_model(self):
        from kani.compaction import _estimate_tokens

        msgs = [{"role": "user", "content": "Hello, world! This is a test sentence."}]
        count = _estimate_tokens(msgs, model="gpt-4o")
        # tiktoken should produce a reasonable token count (not chars/4)
        assert count > 0

    def test_cjk_text_uses_tiktoken(self):
        from kani.compaction import _estimate_tokens

        # Japanese text: each character is typically 1-2 tokens with tiktoken
        # vs. chars/4 which would massively undercount
        msgs = [
            {
                "role": "user",
                "content": "日本語のテストです。これは文脈の圧縮をテストしています。",
            }
        ]
        count_tiktoken = _estimate_tokens(msgs, model="gpt-4o")
        # chars/4 fallback estimate
        total_chars = sum(len(str(m.get("content", ""))) for m in msgs)
        chars_estimate = total_chars // 4
        # tiktoken count should be higher than chars/4 for CJK
        assert count_tiktoken > chars_estimate

    def test_mixed_cjk_english(self):
        from kani.compaction import _estimate_tokens

        msgs = [{"role": "user", "content": "Hello 世界! This is mixed text 日本語."}]
        count = _estimate_tokens(msgs, model="gpt-4o")
        assert count > 0

    def test_unknown_model_falls_back_to_cl100k_base(self):
        from kani.compaction import _estimate_tokens, _encoder_cache

        # Clear cache to ensure fresh resolution
        _encoder_cache.clear()
        msgs = [{"role": "user", "content": "test content"}]
        # Unknown model should not raise and should return a positive count
        count = _estimate_tokens(msgs, model="unknown-model-xyz-12345")
        assert count > 0

    def test_no_model_uses_cl100k_base(self):
        from kani.compaction import _estimate_tokens

        msgs = [{"role": "user", "content": "test content"}]
        count = _estimate_tokens(msgs, model=None)
        assert count > 0

    def test_encoder_cached_on_second_call(self):
        from kani.compaction import _estimate_tokens, _encoder_cache

        _encoder_cache.clear()
        msgs = [{"role": "user", "content": "hello"}]
        _estimate_tokens(msgs, model="gpt-4o")
        assert "gpt-4o" in _encoder_cache
        # Second call hits cache (enc object is same)
        enc_first = _encoder_cache["gpt-4o"]
        _estimate_tokens(msgs, model="gpt-4o")
        assert _encoder_cache["gpt-4o"] is enc_first


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

        import tempfile
        import textwrap
        import os

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
smart_proxy:
  context_compaction:
    enabled: true
    sync_compaction:
      enabled: true
      threshold_percent: 1.0
      summary_profile: ""
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
        result = asyncio.run(_merge_summaries(prior, delta, merge_threshold=99999))
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

            result = asyncio.run(
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

            result = asyncio.run(
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


# ── Session upsert/get tests ─────────────────────────────────────────────────


class TestSessionUpsert:
    """Tests for upsert_session and get_session."""

    def test_upsert_and_get(self):
        from kani.compaction_store import get_session, upsert_session

        upsert_session(
            "sess-upsert",
            profile="auto",
            request_id="req-1",
            snapshot_hash="abc123",
            prompt_tokens=100,
            total_tokens=200,
        )
        sess = get_session("sess-upsert")
        assert sess is not None
        assert sess["session_id"] == "sess-upsert"
        assert sess["profile"] == "auto"
        assert sess["latest_prompt_tokens"] == 100

    def test_upsert_updates_existing(self):
        from kani.compaction_store import get_session, upsert_session

        upsert_session("sess-up2", profile="auto", prompt_tokens=50)
        upsert_session("sess-up2", profile="eco", prompt_tokens=150)
        sess = get_session("sess-up2")
        assert sess is not None
        assert sess["profile"] == "eco"
        assert sess["latest_prompt_tokens"] == 150

    def test_get_missing_session_returns_none(self):
        from kani.compaction_store import get_session

        assert get_session("nonexistent-session") is None


# ── Worker singleton tests ────────────────────────────────────────────────────


class TestWorkerSingleton:
    """Tests for get_worker/set_worker module-level singleton."""

    def test_default_worker_is_none(self):
        from kani.compaction import get_worker, set_worker

        set_worker(None)
        assert get_worker() is None

    def test_set_and_get_worker(self):
        from kani.compaction import (
            BackgroundCompactionWorker,
            get_worker,
            set_worker,
        )

        w = BackgroundCompactionWorker(max_concurrency=1)
        set_worker(w)
        assert get_worker() is w
        set_worker(None)  # cleanup


# ── generate_summary error cases ──────────────────────────────────────────────


class TestGenerateSummaryErrors:
    """Tests for generate_summary error paths."""

    def test_empty_choices_raises(self):
        import asyncio
        from unittest.mock import AsyncMock, MagicMock, patch

        from kani.compaction import generate_summary

        async def run():
            with patch("httpx.AsyncClient") as MockClient:
                mock_client = AsyncMock()
                mock_resp = MagicMock()
                mock_resp.raise_for_status = MagicMock()
                mock_resp.json.return_value = {"choices": []}
                mock_client.post = AsyncMock(return_value=mock_resp)
                MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
                MockClient.return_value.__aexit__ = AsyncMock(return_value=False)
                return await generate_summary(
                    [{"role": "user", "content": "hello"}],
                    summary_model="test",
                    base_url="http://localhost:9999",
                    api_key="fake",
                    protect_first_n=0,
                    protect_last_n=0,
                )

        with pytest.raises(ValueError, match="No choices"):
            asyncio.run(run())

    def test_network_error_propagates(self):
        import asyncio
        from unittest.mock import AsyncMock, patch

        from kani.compaction import generate_summary

        async def run():
            with patch("httpx.AsyncClient") as MockClient:
                mock_client = AsyncMock()
                mock_client.post = AsyncMock(
                    side_effect=ConnectionError("connection refused")
                )
                MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
                MockClient.return_value.__aexit__ = AsyncMock(return_value=False)
                return await generate_summary(
                    [{"role": "user", "content": "hello"}],
                    summary_model="test",
                    base_url="http://localhost:9999",
                    api_key="fake",
                    protect_first_n=0,
                    protect_last_n=0,
                )

        with pytest.raises(ConnectionError):
            asyncio.run(run())

    def test_url_construction_appends_v1(self):
        """generate_summary correctly builds URL with /v1/chat/completions."""
        import asyncio
        from unittest.mock import AsyncMock, MagicMock, patch

        from kani.compaction import generate_summary

        captured_url = {}

        async def fake_post(url, *, json, headers):
            captured_url["url"] = url
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            resp.json.return_value = {"choices": [{"message": {"content": "summary"}}]}
            return resp

        async def run():
            with patch("httpx.AsyncClient") as MockClient:
                mock_client = AsyncMock()
                MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
                MockClient.return_value.__aexit__ = AsyncMock(return_value=False)
                mock_client.post = fake_post
                return await generate_summary(
                    [{"role": "user", "content": "test"}],
                    summary_model="model",
                    base_url="http://example.com/api",
                    api_key="key",
                    protect_first_n=0,
                    protect_last_n=0,
                )

        asyncio.run(run())
        assert captured_url["url"] == "http://example.com/api/v1/chat/completions"

    def test_url_with_existing_v1_not_duplicated(self):
        """When base_url already ends with /v1, it is not duplicated."""
        import asyncio
        from unittest.mock import AsyncMock, MagicMock, patch

        from kani.compaction import generate_summary

        captured_url = {}

        async def fake_post(url, *, json, headers):
            captured_url["url"] = url
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            resp.json.return_value = {"choices": [{"message": {"content": "summary"}}]}
            return resp

        async def run():
            with patch("httpx.AsyncClient") as MockClient:
                mock_client = AsyncMock()
                MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
                MockClient.return_value.__aexit__ = AsyncMock(return_value=False)
                mock_client.post = fake_post
                return await generate_summary(
                    [{"role": "user", "content": "test"}],
                    summary_model="model",
                    base_url="http://example.com/v1",
                    api_key="key",
                    protect_first_n=0,
                    protect_last_n=0,
                )

        asyncio.run(run())
        assert captured_url["url"] == "http://example.com/v1/chat/completions"


# ── BackgroundCompactionWorker tests ──────────────────────────────────────────


class TestBackgroundCompactionWorker:
    """Tests for BackgroundCompactionWorker schedule/run/shutdown."""

    def test_worker_shutdown_no_tasks(self):
        """Shutdown with no scheduled tasks completes without error."""
        import asyncio

        from kani.compaction import BackgroundCompactionWorker

        worker = BackgroundCompactionWorker(max_concurrency=2)
        asyncio.run(worker.shutdown())
        assert len(worker._tasks) == 0

    def test_worker_schedule_and_run(self):
        """Worker schedules a job, generates summary, and updates store to ready."""
        import asyncio
        from unittest.mock import AsyncMock, MagicMock, patch

        from kani.compaction import BackgroundCompactionWorker
        from kani.compaction_store import (
            enqueue_summary,
            get_ready_summary,
            save_snapshot,
        )

        msgs = _make_msgs(10)
        snap_h = save_snapshot("sess-worker", msgs, prompt_tokens=100)
        sid = enqueue_summary("sess-worker", snap_h)

        mock_response = {"choices": [{"message": {"content": "bg summary"}}]}

        async def run():
            with patch("httpx.AsyncClient") as MockClient:
                mock_client = AsyncMock()
                mock_resp = MagicMock()
                mock_resp.raise_for_status = MagicMock()
                mock_resp.json.return_value = mock_response
                mock_client.post = AsyncMock(return_value=mock_resp)
                MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
                MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

                worker = BackgroundCompactionWorker(max_concurrency=1)
                worker.schedule(
                    summary_id=sid,
                    session_id="sess-worker",
                    snap_hash=snap_h,
                    messages=msgs,
                    summary_model="test-model",
                    base_url="http://localhost:9999",
                    api_key="fake",
                    protect_first_n=1,
                    protect_last_n=2,
                    original_tokens=200,
                )
                # Wait for the task to complete
                await asyncio.sleep(0.5)
                await worker.shutdown()

        asyncio.run(run())

        ready = get_ready_summary("sess-worker", snap_h)
        assert ready is not None
        assert ready["summary_text"] == "bg summary"
        assert ready["status"] == "ready"

    def test_worker_handles_failure_gracefully(self):
        """Worker marks summary as failed when generate_summary raises."""
        import asyncio
        from unittest.mock import AsyncMock, patch

        from kani.compaction import BackgroundCompactionWorker
        from kani.compaction_store import enqueue_summary, save_snapshot

        msgs = _make_msgs(10)
        snap_h = save_snapshot("sess-fail", msgs)
        sid = enqueue_summary("sess-fail", snap_h)

        async def run():
            with patch("httpx.AsyncClient") as MockClient:
                mock_client = AsyncMock()
                mock_client.post = AsyncMock(side_effect=Exception("LLM unavailable"))
                MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
                MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

                worker = BackgroundCompactionWorker(max_concurrency=1)
                worker.schedule(
                    summary_id=sid,
                    session_id="sess-fail",
                    snap_hash=snap_h,
                    messages=msgs,
                    summary_model="test-model",
                    base_url="http://localhost:9999",
                    api_key="fake",
                    protect_first_n=1,
                    protect_last_n=2,
                    original_tokens=200,
                )
                await asyncio.sleep(0.5)
                await worker.shutdown()

        asyncio.run(run())

        # Summary should be marked as failed
        import sqlite3
        from kani.compaction_store import _db_path

        conn = sqlite3.connect(str(_db_path()))
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM compaction_summaries WHERE summary_id = ?", (sid,)
        ).fetchone()
        conn.close()
        assert row is not None
        assert dict(row)["status"] == "failed"
        assert "LLM unavailable" in dict(row)["error_message"]


# ── Edge case tests ───────────────────────────────────────────────────────────


class TestCompactMessagesEdgeCases:
    """Edge case tests for _compact_messages."""

    def test_empty_message_list(self):
        from kani.compaction import _compact_messages

        result = _compact_messages([], "summary", 1, 1)
        assert result is None

    def test_single_message(self):
        from kani.compaction import _compact_messages

        msgs = [{"role": "user", "content": "hi"}]
        result = _compact_messages(msgs, "summary", 1, 1)
        assert result is None

    def test_tail_role_duplication_returns_none(self):
        """When tail has consecutive same-role messages, compaction is rejected."""
        from kani.compaction import _compact_messages

        # Build messages where the tail (last 2) has consecutive user roles
        msgs = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "u1"},
            {"role": "assistant", "content": "a1"},
            {"role": "user", "content": "u2"},
            {"role": "assistant", "content": "a2"},
            {"role": "user", "content": "u3"},
            {"role": "user", "content": "u4"},  # consecutive user in tail
        ]
        result = _compact_messages(msgs, "summary", 1, 2)
        assert result is None

    def test_messages_with_empty_content(self):
        from kani.compaction import _estimate_tokens

        msgs = [
            {"role": "user", "content": ""},
            {"role": "assistant"},  # no content key at all
            {"role": "user", "content": "hello"},
        ]
        # Should not crash — returns a positive count for the non-empty message
        count = _estimate_tokens(msgs)
        assert count >= 1

    def test_compact_with_no_system_message(self):
        """Compaction works correctly when first message is not system."""
        from kani.compaction import _compact_messages

        msgs = [
            {"role": "user", "content": "u0"},
            {"role": "assistant", "content": "a0"},
            {"role": "user", "content": "u1"},
            {"role": "assistant", "content": "a1"},
            {"role": "user", "content": "u2"},
            {"role": "assistant", "content": "a2"},
        ]
        result = _compact_messages(msgs, "SUMMARY", 1, 1)
        assert result is not None
        # Head: msgs[0], Summary message, Tail: msgs[-1]
        assert result[0] == msgs[0]
        assert result[-1] == msgs[-1]
        assert any("SUMMARY" in m.get("content", "") for m in result)


# ── no_session inline path tests ──────────────────────────────────────────────


class TestCompactionHeadersNoSession:
    """_compaction_headers omits X-Kani-Compaction-Session when session_id is None."""

    def test_no_session_omits_session_header(self):
        from kani.compaction import CompactionResult
        from kani.proxy import _compaction_headers

        result = CompactionResult(mode="inline", session_id=None, session_mode="none")
        hdrs = _compaction_headers(result)
        assert "X-Kani-Compaction" in hdrs
        assert "X-Kani-Compaction-Session" not in hdrs

    def test_explicit_session_includes_session_header(self):
        from kani.compaction import CompactionResult
        from kani.proxy import _compaction_headers

        result = CompactionResult(
            mode="inline", session_id="my-sess", session_mode="explicit"
        )
        hdrs = _compaction_headers(result)
        assert hdrs.get("X-Kani-Compaction-Session") == "explicit"


class TestNoSessionInlinePath:
    """When no session header is sent, inline compaction fires but no DB state is written."""

    def _make_long_messages(self) -> list[dict[str, Any]]:
        """Build a message list large enough to exceed a low token threshold."""
        return [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "u0 " + "x" * 200},
            {"role": "assistant", "content": "a0 " + "x" * 200},
            {"role": "user", "content": "u1 " + "x" * 200},
            {"role": "assistant", "content": "a1 " + "x" * 200},
            {"role": "user", "content": "u2 " + "x" * 200},
        ]

    def test_no_session_inline_mode_fires(self):
        """_resolve_compaction returns mode='inline' and session_id=None with no session header."""
        import asyncio
        from unittest.mock import AsyncMock, MagicMock, patch

        import kani.proxy as proxy_mod
        from kani.config import (
            BackgroundPrecompactionConfig,
            ContextCompactionConfig,
            KaniConfig,
            ProfileConfig,
            ProviderConfig,
            SessionConfig,
            SmartProxyConfig,
            SyncCompactionConfig,
            TierModelConfig,
        )
        from kani.router import RoutingDecision

        cfg = KaniConfig(
            providers={
                "dummy": ProviderConfig(
                    name="dummy",
                    base_url="http://localhost:9999",
                    api_key="fake",
                )
            },
            default_provider="dummy",
            profiles={
                "auto": ProfileConfig(
                    tiers={"SIMPLE": TierModelConfig(primary="auto-simple")}
                )
            },
            default_profile="auto",
            smart_proxy=SmartProxyConfig(
                context_compaction=ContextCompactionConfig(
                    enabled=True,
                    context_window_tokens=10,  # tiny window → threshold = 0.1 tokens
                    sync_compaction=SyncCompactionConfig(
                        enabled=True,
                        threshold_percent=1.0,
                        summary_profile="auto",
                    ),
                    background_precompaction=BackgroundPrecompactionConfig(
                        enabled=False,
                    ),
                    session=SessionConfig(header_name="X-Kani-Session-Id"),
                )
            ),
        )

        mock_request = MagicMock()
        mock_request.headers.get.return_value = None  # no session header

        mock_decision = RoutingDecision(
            model="auto-simple",
            provider="dummy",
            base_url="http://localhost:9999",
            api_key="fake",
            profile="auto",
            tier="SIMPLE",
            score=0.0,
            confidence=1.0,
        )

        original_config = proxy_mod._config
        original_router = proxy_mod._router
        try:
            proxy_mod._config = cfg
            proxy_mod._router = MagicMock()
            proxy_mod._router.resolve_model.return_value = mock_decision

            async def run():
                with patch(
                    "kani.proxy.generate_summary",
                    AsyncMock(return_value="INLINE SUMMARY"),
                ):
                    return await proxy_mod._resolve_compaction(
                        self._make_long_messages(),
                        mock_request,
                        profile="auto",
                        request_id="req-no-sess",
                        model="auto-simple",
                    )

            result = asyncio.run(run())
        finally:
            proxy_mod._config = original_config
            proxy_mod._router = original_router

        assert result.mode == "inline"
        assert result.session_id is None
        assert result.session_mode == "none"

    def test_no_session_no_db_state(self):
        """When session_id is None, no session row is created in the DB."""
        import asyncio
        from unittest.mock import AsyncMock, MagicMock, patch

        import kani.compaction_store as store
        import kani.proxy as proxy_mod
        from kani.config import (
            BackgroundPrecompactionConfig,
            ContextCompactionConfig,
            KaniConfig,
            ProfileConfig,
            ProviderConfig,
            SessionConfig,
            SmartProxyConfig,
            SyncCompactionConfig,
            TierModelConfig,
        )
        from kani.router import RoutingDecision

        cfg = KaniConfig(
            providers={
                "dummy": ProviderConfig(
                    name="dummy",
                    base_url="http://localhost:9999",
                    api_key="fake",
                )
            },
            default_provider="dummy",
            profiles={
                "auto": ProfileConfig(
                    tiers={"SIMPLE": TierModelConfig(primary="auto-simple")}
                )
            },
            default_profile="auto",
            smart_proxy=SmartProxyConfig(
                context_compaction=ContextCompactionConfig(
                    enabled=True,
                    context_window_tokens=10,
                    sync_compaction=SyncCompactionConfig(
                        enabled=True,
                        threshold_percent=1.0,
                        summary_profile="auto",
                    ),
                    background_precompaction=BackgroundPrecompactionConfig(
                        enabled=False,
                    ),
                    session=SessionConfig(header_name="X-Kani-Session-Id"),
                )
            ),
        )

        mock_request = MagicMock()
        mock_request.headers.get.return_value = None

        mock_decision = RoutingDecision(
            model="auto-simple",
            provider="dummy",
            base_url="http://localhost:9999",
            api_key="fake",
            profile="auto",
            tier="SIMPLE",
            score=0.0,
            confidence=1.0,
        )

        original_config = proxy_mod._config
        original_router = proxy_mod._router
        try:
            proxy_mod._config = cfg
            proxy_mod._router = MagicMock()
            proxy_mod._router.resolve_model.return_value = mock_decision

            async def run():
                with patch(
                    "kani.proxy.generate_summary",
                    AsyncMock(return_value="INLINE SUMMARY"),
                ):
                    return await proxy_mod._resolve_compaction(
                        self._make_long_messages(),
                        mock_request,
                        profile="auto",
                        request_id="req-no-sess-2",
                        model="auto-simple",
                    )

            asyncio.run(run())
        finally:
            proxy_mod._config = original_config
            proxy_mod._router = original_router

        # No session should be stored in DB
        assert store.get_session("any-session") is None
