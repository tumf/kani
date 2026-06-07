"""Tests for context-window-aware routing."""

from __future__ import annotations

from kani.config import (
    KaniConfig,
    ModelCapabilityEntry,
    ProviderConfig,
    ProfileConfig,
    TierModelConfig,
)
from kani.fallback_backoff import FallbackBackoffState
from kani.router import Router


def _messages(tokenish_length: int = 160) -> list[dict[str, str]]:
    return [{"role": "user", "content": "x " * tokenish_length}]


def _config(*, tiers: dict[str, TierModelConfig], capabilities: list[ModelCapabilityEntry] | None = None) -> KaniConfig:
    return KaniConfig(
        providers={
            "default": ProviderConfig(
                name="default",
                base_url="https://default.example/v1",
                api_key="default-key",
            ),
            "tier-provider": ProviderConfig(
                name="tier-provider",
                base_url="https://tier.example/v1",
                api_key="tier-key",
            ),
            "entry-provider": ProviderConfig(
                name="entry-provider",
                base_url="https://entry.example/v1",
                api_key="entry-key",
            ),
        },
        default_provider="default",
        profiles={"auto": ProfileConfig(tiers=tiers)},
        default_profile="auto",
        model_capabilities=capabilities or [],
    )


def _all_tiers(primary: str | dict[str, object], **overrides: TierModelConfig) -> dict[str, TierModelConfig]:
    tiers = {
        "SIMPLE": TierModelConfig(primary=primary),
        "MEDIUM": TierModelConfig(primary=primary),
        "COMPLEX": TierModelConfig(primary=primary),
        "REASONING": TierModelConfig(primary=primary),
    }
    tiers.update(overrides)
    return tiers


def _force_tier(router: Router, tier: str) -> None:
    router._classify = lambda *args, **kwargs: {  # type: ignore[method-assign]
        "tier": tier,
        "score": 0.5,
        "confidence": 1.0,
        "signals": [],
        "agentic_score": 0.0,
    }


class TestContextWindowConfig:
    def test_model_entry_accepts_context_window_and_string_entries_still_validate(self) -> None:
        cfg = _config(
            tiers=_all_tiers(
                "string-model",
                MEDIUM=TierModelConfig(
                    primary=[
                        "string-model",
                        {"model": "object-model", "provider": "entry-provider", "context_window_tokens": 8192},
                    ],
                    fallback=[{"model": "fallback-model", "context_window_tokens": 16384}],
                ),
            )
        )

        tier = cfg.profiles["auto"].tiers["MEDIUM"]
        primary_entries = tier.resolve_primary_candidate_entries()
        fallback_entries = tier.resolve_fallback_candidate_entries()

        assert primary_entries[0].model == "string-model"
        assert primary_entries[0].context_window_tokens is None
        assert primary_entries[1].model == "object-model"
        assert primary_entries[1].provider == "entry-provider"
        assert primary_entries[1].context_window_tokens == 8192
        assert fallback_entries[0].context_window_tokens == 16384
        assert tier.resolve_primary_candidates() == [("string-model", ""), ("object-model", "entry-provider")]

    def test_provider_precedence_survives_candidate_metadata(self) -> None:
        cfg = _config(
            tiers=_all_tiers(
                "unused",
                MEDIUM=TierModelConfig(
                    primary=[
                        {"model": "tier-default-model", "context_window_tokens": 99999},
                        {"model": "entry-provider-model", "provider": "entry-provider", "context_window_tokens": 99999},
                    ],
                    provider="tier-provider",
                ),
            )
        )
        router = Router(cfg)
        _force_tier(router, "MEDIUM")

        first = router.route(_messages(), profile="auto")
        second = router.route(_messages(), profile="auto")

        assert first.model == "tier-default-model"
        assert first.provider == "tier-provider"
        assert second.model == "entry-provider-model"
        assert second.provider == "entry-provider"


class TestContextWindowRouting:
    def test_long_request_skips_too_small_primary(self) -> None:
        cfg = _config(
            tiers=_all_tiers(
                "unused",
                MEDIUM=TierModelConfig(
                    primary=[
                        {"model": "small", "context_window_tokens": 4},
                        {"model": "large", "context_window_tokens": 99999},
                    ],
                ),
            )
        )
        router = Router(cfg)
        _force_tier(router, "MEDIUM")

        decision = router.route(_messages(), profile="auto")

        assert decision.model == "large"

    def test_unknown_context_window_remains_eligible(self) -> None:
        cfg = _config(
            tiers=_all_tiers(
                "unused",
                MEDIUM=TierModelConfig(
                    primary=[
                        {"model": "small", "context_window_tokens": 4},
                        "unknown-window",
                    ],
                ),
            )
        )
        router = Router(cfg)
        _force_tier(router, "MEDIUM")

        decision = router.route(_messages(), profile="auto")

        assert decision.model == "unknown-window"

    def test_fallback_can_satisfy_long_context(self) -> None:
        cfg = _config(
            tiers=_all_tiers(
                "unused",
                MEDIUM=TierModelConfig(
                    primary=[{"model": "small-primary", "context_window_tokens": 4}],
                    fallback=[{"model": "large-fallback", "context_window_tokens": 99999}],
                ),
            )
        )
        router = Router(cfg)
        _force_tier(router, "MEDIUM")

        decision = router.route(_messages(), profile="auto")

        assert decision.model == "large-fallback"
        assert decision.fallbacks == []

    def test_higher_tier_can_satisfy_long_context(self) -> None:
        cfg = _config(
            tiers={
                "MEDIUM": TierModelConfig(primary=[{"model": "small-medium", "context_window_tokens": 4}]),
                "COMPLEX": TierModelConfig(primary=[{"model": "large-complex", "context_window_tokens": 99999}]),
            }
        )
        router = Router(cfg)
        _force_tier(router, "MEDIUM")

        decision = router.route(_messages(), profile="auto")

        assert decision.model == "large-complex"
        assert decision.reasoning_effort is None

    def test_capability_filtering_remains_mandatory_with_large_context_candidate(self) -> None:
        cfg = _config(
            tiers=_all_tiers(
                "unused",
                MEDIUM=TierModelConfig(
                    primary=[
                        {"model": "large-text", "context_window_tokens": 99999},
                        {"model": "large-vision", "context_window_tokens": 99999},
                    ],
                ),
            ),
            capabilities=[
                ModelCapabilityEntry(prefix="large-text", capabilities=[]),
                ModelCapabilityEntry(prefix="large-vision", capabilities=["vision"]),
            ],
        )
        router = Router(cfg)

        decision = router.route(_messages(), profile="auto", required_capabilities={"vision"})

        assert decision.model == "large-vision"

    def test_cooldown_applies_after_context_filtering(self) -> None:
        cfg = _config(
            tiers=_all_tiers(
                "unused",
                MEDIUM=TierModelConfig(
                    primary=[
                        {"model": "small", "context_window_tokens": 4},
                        {"model": "large-cooled", "context_window_tokens": 99999},
                        {"model": "large-ready", "context_window_tokens": 99999},
                    ],
                ),
            )
        )
        state = FallbackBackoffState(cfg.smart_proxy.fallback_backoff.model_copy(update={"enabled": True}))
        state.record_retryable_failure("large-cooled", "default")
        router = Router(cfg, fallback_backoff_state=state)
        _force_tier(router, "MEDIUM")

        decision = router.route(_messages(), profile="auto")

        assert decision.model == "large-ready"
