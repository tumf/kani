from __future__ import annotations

from unittest.mock import patch

from kani.config import KaniConfig, ProfileConfig, ProviderConfig, TierModelConfig
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
    def test_route_logs_signal_details_without_changing_public_signal_list(
        self,
    ) -> None:
        router = Router(_make_config())
        detailed_signals = {
            "method": {"raw": "embedding", "matches": 0},
            "agenticLabel": {"raw": "AGENTIC", "matches": 0},
            "agenticMethod": {"raw": "llm", "matches": 0},
        }

        with (
            patch.object(
                Router,
                "_classify",
                return_value={
                    "tier": "SIMPLE",
                    "score": 0.9,
                    "confidence": 0.92,
                    "signals": ["method", "agenticLabel", "agenticMethod"],
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

        assert decision.signals == ["method", "agenticLabel", "agenticMethod"]
        assert decision.tier == "MEDIUM"
        mock_log.assert_called_once()
        assert mock_log.call_args.kwargs["signals"] == detailed_signals

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
                "signal_details": {"method": {"raw": "embedding"}},
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
