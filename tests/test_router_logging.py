"""Tests for router integration with distilled feature scoring and logging."""

from __future__ import annotations

from unittest.mock import patch

from kani.config import KaniConfig, ProfileConfig, ProviderConfig, TierModelConfig
from kani.fallback_backoff import FallbackBackoffState
from kani.router import Router


def _make_config() -> KaniConfig:
    return KaniConfig(
        providers={
            "openrouter": ProviderConfig(
                name="openrouter",
                base_url="https://openrouter.ai/api/v1",
                api_key="test-key",
            )
        },
        default_provider="openrouter",
        profiles={
            "agentic": ProfileConfig(
                tiers={
                    "SIMPLE": TierModelConfig(primary="model-simple"),
                    "MEDIUM": TierModelConfig(primary="model-medium"),
                    "COMPLEX": TierModelConfig(primary="model-complex"),
                    "REASONING": TierModelConfig(primary="model-reasoning"),
                }
            )
        },
        default_profile="agentic",
    )


class TestRouterLogging:
    def test_route_uses_context_aware_classification_input_for_short_followup(
        self,
    ) -> None:
        router = Router(_make_config())

        with patch.object(
            Router,
            "_classify",
            return_value={
                "tier": "MEDIUM",
                "score": 0.3,
                "confidence": 0.9,
                "signals": ["method"],
                "signal_details": {"method": {"raw": "distilled-features"}},
                "agentic_score": 0.0,
            },
        ) as mock_classify:
            router.route(
                [
                    {
                        "role": "system",
                        "content": "Follow repository coding rules",
                    },
                    {
                        "role": "user",
                        "content": "Refactor router and add tests for edge cases",
                    },
                    {
                        "role": "assistant",
                        "content": "了解しました。次に何をしますか？",
                    },
                    {
                        "role": "user",
                        "content": "続けて",
                    },
                ],
                profile="agentic",
            )

        assert mock_classify.call_count == 1
        classification_input = mock_classify.call_args.kwargs["classification_input"]
        assert "続けて" in classification_input.text
        assert (
            "Refactor router and add tests for edge cases" in classification_input.text
        )
        assert classification_input.last_user_is_short_followup is True

    def test_route_logs_signal_details_without_changing_public_signal_list(
        self,
    ) -> None:
        router = Router(_make_config())
        detailed_signals = {
            "method": {"raw": "distilled-features", "matches": 0},
            "tokenCount": 42,
            "semanticLabels": {
                "agenticTask": "high",
                "reasoningMarkers": "medium",
            },
            "featureVersion": "v1",
        }

        with (
            patch.object(
                Router,
                "_classify",
                return_value={
                    "tier": "SIMPLE",
                    "score": 0.9,
                    "confidence": 0.92,
                    "signals": [
                        "method",
                        "tokenCount",
                        "semanticLabels",
                        "featureVersion",
                    ],
                    "signal_details": detailed_signals,
                    "agentic_score": 1.0,
                },
            ),
            patch("kani.logger.RoutingLogger.log_decision") as mock_log,
        ):
            decision = router.route(
                [
                    {
                        "role": "user",
                        "content": "Open the repo and update the config file",
                    }
                ],
                profile="agentic",
            )

        assert decision.signals == [
            "method",
            "tokenCount",
            "semanticLabels",
            "featureVersion",
        ]
        assert decision.tier == "MEDIUM"
        mock_log.assert_called_once()
        assert mock_log.call_args.kwargs["signals"] == detailed_signals
        context = mock_log.call_args.kwargs["context"]
        assert context["text"]
        assert "Open the repo and update the config file" in context["text"]

    def test_round_robin_primary_selection_per_profile_tier(self) -> None:
        config = KaniConfig(
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
                        "SIMPLE": TierModelConfig(
                            primary=["model-a", "model-b"],
                            fallback=[],
                        ),
                        "MEDIUM": TierModelConfig(primary="model-medium", fallback=[]),
                    }
                ),
                "eco": ProfileConfig(
                    tiers={
                        "SIMPLE": TierModelConfig(primary=["eco-a", "eco-b"]),
                        "MEDIUM": TierModelConfig(primary="eco-medium"),
                    }
                ),
            },
            default_profile="auto",
        )
        router = Router(config)

        with patch.object(
            Router,
            "_classify",
            return_value={
                "tier": "SIMPLE",
                "score": 0.1,
                "confidence": 0.9,
                "signals": ["method"],
                "signal_details": {"method": {"raw": "distilled-features"}},
                "agentic_score": 0.0,
            },
        ):
            auto_1 = router.route([{"role": "user", "content": "hi"}], profile="auto")
            auto_2 = router.route([{"role": "user", "content": "hi"}], profile="auto")
            eco_1 = router.route([{"role": "user", "content": "hi"}], profile="eco")
            auto_3 = router.route([{"role": "user", "content": "hi"}], profile="auto")
            eco_2 = router.route([{"role": "user", "content": "hi"}], profile="eco")

        assert [auto_1.model, auto_2.model, auto_3.model] == [
            "model-a",
            "model-b",
            "model-a",
        ]
        assert [eco_1.model, eco_2.model] == ["eco-a", "eco-b"]

    def test_round_robin_skips_cooled_primary_candidates(self) -> None:
        config = KaniConfig(
            providers={
                "openrouter": ProviderConfig(
                    name="openrouter",
                    base_url="https://openrouter.ai/api/v1",
                    api_key="test-key",
                ),
                "alt": ProviderConfig(
                    name="alt",
                    base_url="https://alt.example/v1",
                    api_key="alt-key",
                ),
            },
            default_provider="openrouter",
            profiles={
                "auto": ProfileConfig(
                    tiers={
                        "SIMPLE": TierModelConfig(
                            primary=["model-a", "model-b"],
                            fallback=[],
                        ),
                        "MEDIUM": TierModelConfig(primary="model-medium", fallback=[]),
                    }
                )
            },
            default_profile="auto",
            smart_proxy={
                "fallback_backoff": {
                    "enabled": True,
                    "initial_delay_seconds": 5,
                    "multiplier": 2,
                    "max_delay_seconds": 60,
                }
            },
        )
        backoff_state = FallbackBackoffState(config.smart_proxy.fallback_backoff)
        backoff_state.record_retryable_failure("model-a", "openrouter")
        router = Router(config, fallback_backoff_state=backoff_state)

        with patch.object(
            Router,
            "_classify",
            return_value={
                "tier": "SIMPLE",
                "score": 0.1,
                "confidence": 0.9,
                "signals": ["method"],
                "signal_details": {"method": {"raw": "distilled-features"}},
                "agentic_score": 0.0,
            },
        ):
            first = router.route([{"role": "user", "content": "hi"}], profile="auto")
            second = router.route([{"role": "user", "content": "hi"}], profile="auto")

        assert first.model == "model-b"
        assert second.model == "model-b"
