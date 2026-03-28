"""Tests for capability-aware routing."""

from __future__ import annotations

import pytest

from kani.config import (
    KaniConfig,
    ModelCapabilityEntry,
    ProviderConfig,
    ProfileConfig,
    TierModelConfig,
)
from kani.router import CapabilityNotSatisfiedError, Router


class TestCapabilityDetection:
    """Test capability detection from request bodies."""

    def test_detect_vision_capability(self) -> None:
        """Vision capability should be detected when image_url is present."""
        from kani.proxy import _detect_required_capabilities

        body = {
            "model": "gpt-4",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "What's in this image?"},
                        {
                            "type": "image_url",
                            "image_url": {"url": "https://example.com/img.png"},
                        },
                    ],
                }
            ],
        }
        caps = _detect_required_capabilities(body)
        assert "vision" in caps

    def test_detect_tools_capability_via_tools_field(self) -> None:
        """Tools capability should be detected when tools field is present."""
        from kani.proxy import _detect_required_capabilities

        body = {
            "model": "gpt-4",
            "messages": [{"role": "user", "content": "Help me call a tool"}],
            "tools": [{"type": "function", "function": {"name": "test"}}],
        }
        caps = _detect_required_capabilities(body)
        assert "tools" in caps

    def test_detect_tools_capability_via_functions_field(self) -> None:
        """Tools capability should be detected when functions field is present."""
        from kani.proxy import _detect_required_capabilities

        body = {
            "model": "gpt-4",
            "messages": [{"role": "user", "content": "Help me call a function"}],
            "functions": [{"name": "test"}],
        }
        caps = _detect_required_capabilities(body)
        assert "tools" in caps

    def test_detect_json_mode_capability(self) -> None:
        """JSON mode capability should be detected when response_format is json."""
        from kani.proxy import _detect_required_capabilities

        body = {
            "model": "gpt-4",
            "messages": [{"role": "user", "content": "Give me JSON"}],
            "response_format": {"type": "json_object"},
        }
        caps = _detect_required_capabilities(body)
        assert "json_mode" in caps

    def test_detect_json_schema_mode(self) -> None:
        """JSON mode should be detected for json_schema response format."""
        from kani.proxy import _detect_required_capabilities

        body = {
            "model": "gpt-4",
            "messages": [{"role": "user", "content": "Give me JSON"}],
            "response_format": {"type": "json_schema", "schema": {}},
        }
        caps = _detect_required_capabilities(body)
        assert "json_mode" in caps

    def test_detect_multiple_capabilities(self) -> None:
        """Multiple capabilities should be detected together."""
        from kani.proxy import _detect_required_capabilities

        body = {
            "model": "gpt-4",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Look at this and call a tool"},
                        {
                            "type": "image_url",
                            "image_url": {"url": "https://example.com/img.png"},
                        },
                    ],
                }
            ],
            "tools": [{"type": "function", "function": {"name": "analyze"}}],
            "response_format": {"type": "json_object"},
        }
        caps = _detect_required_capabilities(body)
        assert "vision" in caps
        assert "tools" in caps
        assert "json_mode" in caps

    def test_no_capabilities_required(self) -> None:
        """No capabilities should be detected for simple text-only request."""
        from kani.proxy import _detect_required_capabilities

        body = {
            "model": "gpt-4",
            "messages": [{"role": "user", "content": "Simple text question"}],
        }
        caps = _detect_required_capabilities(body)
        assert len(caps) == 0


class TestCapabilityFiltering:
    """Test capability-based model filtering in the router."""

    def _make_config(
        self,
        model_capabilities: list[ModelCapabilityEntry] | None = None,
    ) -> KaniConfig:
        """Create a test config with model capabilities."""
        if model_capabilities is None:
            model_capabilities = [
                ModelCapabilityEntry(
                    prefix="gpt-4", capabilities=["vision", "tools", "json_mode"]
                ),
                ModelCapabilityEntry(
                    prefix="gpt-4o", capabilities=["vision", "tools", "json_mode"]
                ),
                ModelCapabilityEntry(
                    prefix="gpt-4o-mini", capabilities=["vision", "tools", "json_mode"]
                ),
                ModelCapabilityEntry(
                    prefix="claude-opus", capabilities=["vision", "tools", "json_mode"]
                ),
                ModelCapabilityEntry(
                    prefix="claude-sonnet",
                    capabilities=["vision", "tools", "json_mode"],
                ),
                ModelCapabilityEntry(
                    prefix="claude-haiku", capabilities=["tools"]
                ),  # no vision
            ]

        return KaniConfig(
            host="0.0.0.0",
            port=18420,
            providers={
                "default": ProviderConfig(
                    name="default",
                    base_url="https://api.example.com/v1",
                    api_key="test-key",
                )
            },
            default_provider="default",
            profiles={
                "auto": ProfileConfig(
                    tiers={
                        "SIMPLE": TierModelConfig(
                            primary=["gpt-4o-mini", "claude-haiku"],
                        ),
                        "MEDIUM": TierModelConfig(
                            primary=["gpt-4o", "claude-sonnet"],
                        ),
                        "COMPLEX": TierModelConfig(
                            primary="gpt-4",
                            fallback=["claude-opus"],
                        ),
                        "REASONING": TierModelConfig(
                            primary="gpt-4",
                        ),
                    }
                )
            },
            default_profile="auto",
            model_capabilities=model_capabilities,
        )

    def test_filter_capable_candidates_with_vision(self) -> None:
        """Only models with vision should be selected."""
        config = self._make_config()
        router = Router(config)

        candidates = [("gpt-4o-mini", ""), ("claude-haiku", "")]
        capable = router._filter_capable_candidates(candidates, {"vision"})

        # gpt-4o-mini has vision, claude-haiku doesn't
        assert len(capable) == 1
        assert capable[0][0] == "gpt-4o-mini"

    def test_filter_capable_candidates_with_tools(self) -> None:
        """Both models should have tools capability."""
        config = self._make_config()
        router = Router(config)

        candidates = [("gpt-4o-mini", ""), ("claude-haiku", "")]
        capable = router._filter_capable_candidates(candidates, {"tools"})

        # Both have tools
        assert len(capable) == 2

    def test_filter_capable_candidates_with_multiple_required(self) -> None:
        """Only models with all required capabilities should be selected."""
        config = self._make_config()
        router = Router(config)

        candidates = [("gpt-4o-mini", ""), ("claude-haiku", "")]
        capable = router._filter_capable_candidates(candidates, {"vision", "tools"})

        # Only gpt-4o-mini has both vision and tools
        assert len(capable) == 1
        assert capable[0][0] == "gpt-4o-mini"

    def test_no_filter_when_no_capabilities_required(self) -> None:
        """All candidates should pass when no capabilities are required."""
        config = self._make_config()
        router = Router(config)

        candidates = [("gpt-4o-mini", ""), ("claude-haiku", "")]
        capable = router._filter_capable_candidates(candidates, set())

        assert len(capable) == 2

    def test_get_model_capabilities_by_prefix(self) -> None:
        """Model capabilities should be resolved by prefix matching."""
        config = self._make_config()
        router = Router(config)

        # Exact prefix match
        caps = router._get_model_capabilities("gpt-4o-mini")
        assert "vision" in caps
        assert "tools" in caps

        # Longer model ID with matching prefix
        caps = router._get_model_capabilities("gpt-4-turbo-20250101")
        assert "vision" in caps
        assert "tools" in caps

    def test_get_model_capabilities_unknown_model(self) -> None:
        """Unknown models should return empty capability set."""
        config = self._make_config()
        router = Router(config)

        caps = router._get_model_capabilities("unknown-model-xyz")
        assert len(caps) == 0


class TestCapabilityEscalation:
    """Test tier escalation when no capable models in current tier."""

    def test_escalate_when_no_capable_primary(self) -> None:
        """Router should escalate to higher tiers when primary tier has no capable models."""
        config = KaniConfig(
            host="0.0.0.0",
            port=18420,
            providers={
                "default": ProviderConfig(
                    name="default",
                    base_url="https://api.example.com/v1",
                    api_key="test-key",
                )
            },
            default_provider="default",
            profiles={
                "auto": ProfileConfig(
                    tiers={
                        "SIMPLE": TierModelConfig(
                            primary="gpt-4o-mini",  # has vision
                        ),
                        "MEDIUM": TierModelConfig(
                            primary="claude-haiku",  # no vision
                        ),
                        "COMPLEX": TierModelConfig(
                            primary="gpt-4",  # has vision
                        ),
                        "REASONING": TierModelConfig(
                            primary="gpt-4",
                        ),
                    }
                )
            },
            default_profile="auto",
            model_capabilities=[
                ModelCapabilityEntry(
                    prefix="gpt-4", capabilities=["vision", "tools", "json_mode"]
                ),
                ModelCapabilityEntry(
                    prefix="gpt-4o", capabilities=["vision", "tools", "json_mode"]
                ),
                ModelCapabilityEntry(
                    prefix="claude-haiku", capabilities=["tools"]
                ),  # no vision
            ],
        )
        router = Router(config)

        # Test that _escalation_path works correctly
        # Verify escalation path from MEDIUM goes to COMPLEX and REASONING
        profile_cfg = config.profiles["auto"]
        escalation = router._escalation_path(profile_cfg, "MEDIUM")
        assert "COMPLEX" in escalation

    def test_escalation_path_from_medium(self) -> None:
        """Escalation path from MEDIUM should go to COMPLEX then REASONING."""
        config = KaniConfig(
            host="0.0.0.0",
            port=18420,
            providers={
                "default": ProviderConfig(
                    name="default",
                    base_url="https://api.example.com/v1",
                    api_key="test-key",
                )
            },
            default_provider="default",
            profiles={
                "auto": ProfileConfig(
                    tiers={
                        "SIMPLE": TierModelConfig(primary="model"),
                        "MEDIUM": TierModelConfig(primary="model"),
                        "COMPLEX": TierModelConfig(primary="model"),
                        "REASONING": TierModelConfig(primary="model"),
                    }
                )
            },
            default_profile="auto",
        )
        router = Router(config)

        profile_cfg = config.profiles["auto"]
        path = router._escalation_path(profile_cfg, "MEDIUM")

        assert "COMPLEX" in path
        assert "REASONING" in path
        # COMPLEX should come before REASONING
        assert path.index("COMPLEX") < path.index("REASONING")

    def test_capability_not_satisfied_error(self) -> None:
        """Should raise CapabilityNotSatisfiedError when no model has required capability."""
        config = KaniConfig(
            host="0.0.0.0",
            port=18420,
            providers={
                "default": ProviderConfig(
                    name="default",
                    base_url="https://api.example.com/v1",
                    api_key="test-key",
                )
            },
            default_provider="default",
            profiles={
                "auto": ProfileConfig(
                    tiers={
                        "SIMPLE": TierModelConfig(primary="text-model"),
                        "MEDIUM": TierModelConfig(primary="text-model"),
                        "COMPLEX": TierModelConfig(primary="text-model"),
                        "REASONING": TierModelConfig(primary="text-model"),
                    }
                )
            },
            default_profile="auto",
            model_capabilities=[
                ModelCapabilityEntry(
                    prefix="text-model", capabilities=[]
                ),  # no capabilities
            ],
        )
        router = Router(config)

        messages = [{"role": "user", "content": "test"}]

        with pytest.raises(CapabilityNotSatisfiedError) as exc_info:
            router.route(messages, profile="auto", required_capabilities={"vision"})

        assert exc_info.value.required_capabilities == {"vision"}
        assert "vision" in str(exc_info.value).lower()

    def test_backward_compat_no_capabilities_configured(self) -> None:
        """Routing should work normally when no capabilities are configured."""
        config = KaniConfig(
            host="0.0.0.0",
            port=18420,
            providers={
                "default": ProviderConfig(
                    name="default",
                    base_url="https://api.example.com/v1",
                    api_key="test-key",
                )
            },
            default_provider="default",
            profiles={
                "auto": ProfileConfig(
                    tiers={
                        "SIMPLE": TierModelConfig(primary="any-model"),
                        "MEDIUM": TierModelConfig(primary="any-model"),
                        "COMPLEX": TierModelConfig(primary="any-model"),
                        "REASONING": TierModelConfig(primary="any-model"),
                    }
                )
            },
            default_profile="auto",
            model_capabilities=[],  # empty
        )
        router = Router(config)

        messages = [{"role": "user", "content": "test"}]

        # Should succeed without required_capabilities
        decision = router.route(messages, profile="auto")
        assert decision.model == "any-model"

    def test_no_capabilities_configured_returns_empty_for_required(self) -> None:
        """When no capabilities configured, models have no capabilities and fail requirements."""
        config = KaniConfig(
            host="0.0.0.0",
            port=18420,
            providers={
                "default": ProviderConfig(
                    name="default",
                    base_url="https://api.example.com/v1",
                    api_key="test-key",
                )
            },
            default_provider="default",
            profiles={
                "auto": ProfileConfig(
                    tiers={
                        "SIMPLE": TierModelConfig(primary="basic-model"),
                        "MEDIUM": TierModelConfig(primary="basic-model"),
                        "COMPLEX": TierModelConfig(primary="basic-model"),
                        "REASONING": TierModelConfig(primary="basic-model"),
                    }
                )
            },
            default_profile="auto",
            model_capabilities=[],  # empty - no capabilities declared
        )
        router = Router(config)

        # When no capabilities are configured, models have empty capabilities
        # and cannot satisfy vision requirement → CapabilityNotSatisfiedError
        with pytest.raises(CapabilityNotSatisfiedError):
            router.route(
                [{"role": "user", "content": "test"}],
                profile="auto",
                required_capabilities={"vision"},
            )
