from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from kani.config import KaniConfig, load_config
from kani.fallback_backoff import FallbackBackoffState


class TestFallbackBackoffConfig:
    def test_defaults_are_loaded(self) -> None:
        cfg = load_config(overrides={})

        backoff = cfg.smart_proxy.fallback_backoff
        assert backoff.enabled is False
        assert backoff.initial_delay_seconds == 5.0
        assert backoff.multiplier == 2.0
        assert backoff.max_delay_seconds == 300.0

    def test_parses_overrides(self) -> None:
        cfg = load_config(
            overrides={
                "smart_proxy": {
                    "fallback_backoff": {
                        "enabled": True,
                        "initial_delay_seconds": 3,
                        "multiplier": 4,
                        "max_delay_seconds": 30,
                    }
                }
            }
        )

        backoff = cfg.smart_proxy.fallback_backoff
        assert backoff.enabled is True
        assert backoff.initial_delay_seconds == 3
        assert backoff.multiplier == 4
        assert backoff.max_delay_seconds == 30

    def test_rejects_max_delay_below_initial_delay(self) -> None:
        with pytest.raises(ValueError, match="max_delay_seconds"):
            load_config(
                overrides={
                    "smart_proxy": {
                        "fallback_backoff": {
                            "initial_delay_seconds": 10,
                            "max_delay_seconds": 5,
                        }
                    }
                }
            )


class TestFallbackBackoffState:
    def test_failure_streak_grows_exponentially(self) -> None:
        cfg = KaniConfig.model_validate(
            {
                "smart_proxy": {
                    "fallback_backoff": {
                        "enabled": True,
                        "initial_delay_seconds": 2,
                        "multiplier": 3,
                        "max_delay_seconds": 99,
                    }
                }
            }
        )
        state = FallbackBackoffState(cfg.smart_proxy.fallback_backoff)
        now = datetime(2026, 1, 1, tzinfo=UTC)

        first = state.record_retryable_failure("model-a", "provider-a", now=now)
        second = state.record_retryable_failure(
            "model-a", "provider-a", now=now + timedelta(seconds=1)
        )

        assert first.failure_streak == 1
        assert first.cooldown_until == now + timedelta(seconds=2)
        assert second.failure_streak == 2
        assert second.cooldown_until == now + timedelta(seconds=7)

    def test_failure_delay_is_clamped_to_max(self) -> None:
        cfg = KaniConfig.model_validate(
            {
                "smart_proxy": {
                    "fallback_backoff": {
                        "enabled": True,
                        "initial_delay_seconds": 5,
                        "multiplier": 10,
                        "max_delay_seconds": 20,
                    }
                }
            }
        )
        state = FallbackBackoffState(cfg.smart_proxy.fallback_backoff)
        now = datetime(2026, 1, 1, tzinfo=UTC)

        state.record_retryable_failure("model-a", "provider-a", now=now)
        capped = state.record_retryable_failure(
            "model-a", "provider-a", now=now + timedelta(seconds=1)
        )

        assert capped.cooldown_until == now + timedelta(seconds=21)

    def test_success_resets_streak(self) -> None:
        cfg = KaniConfig.model_validate(
            {
                "smart_proxy": {
                    "fallback_backoff": {
                        "enabled": True,
                        "initial_delay_seconds": 2,
                        "multiplier": 2,
                        "max_delay_seconds": 20,
                    }
                }
            }
        )
        state = FallbackBackoffState(cfg.smart_proxy.fallback_backoff)
        now = datetime(2026, 1, 1, tzinfo=UTC)

        state.record_retryable_failure("model-a", "provider-a", now=now)
        assert state.record_success("model-a", "provider-a") is True
        assert state.get_entry("model-a", "provider-a") is None
        reset = state.record_retryable_failure(
            "model-a", "provider-a", now=now + timedelta(seconds=10)
        )

        assert reset.failure_streak == 1
        assert reset.cooldown_until == now + timedelta(seconds=12)
