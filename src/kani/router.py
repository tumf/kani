"""Kani smart router – maps incoming messages to the best model+provider."""

from __future__ import annotations

import logging
from threading import Lock
from typing import Any

from pydantic import BaseModel, Field

from kani.config import KaniConfig, ProviderConfig, resolve_env

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------


class CapabilityNotSatisfiedError(Exception):
    """Raised when no model with required capabilities is available."""

    def __init__(self, required_capabilities: set[str]) -> None:
        self.required_capabilities = required_capabilities
        caps_str = ", ".join(sorted(required_capabilities))
        super().__init__(
            f"No available model supports required capabilities: {caps_str}"
        )


# ---------------------------------------------------------------------------
# Routing result
# ---------------------------------------------------------------------------


class FallbackEntry(BaseModel):
    """A fallback model with provider connection info."""

    model: str
    provider: str
    base_url: str
    api_key: str = ""


class RoutingDecision(BaseModel):
    """The outcome of a routing decision."""

    model: str
    provider: str
    base_url: str
    api_key: str = ""
    tier: str
    score: float
    confidence: float
    signals: list[str] = Field(default_factory=list)
    agentic_score: float = 0.0
    profile: str | None = None
    fallbacks: list[FallbackEntry] = Field(default_factory=list)
    required_capabilities: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

# Default tier when the scorer can't decide
_DEFAULT_TIER = "MEDIUM"

# Ordered tiers from simplest to most complex
_TIER_ORDER = ["SIMPLE", "MEDIUM", "COMPLEX", "REASONING"]


class Router:
    """Given chat messages, decides which model and provider to use."""

    def __init__(self, config: KaniConfig) -> None:
        self.config = config
        self._rr_state: dict[tuple[str, str], int] = {}
        self._rr_lock = Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def route(
        self,
        messages: list[dict[str, Any]],
        *,
        profile: str | None = None,
        model: str | None = None,
        required_capabilities: set[str] | None = None,
    ) -> RoutingDecision:
        """Route a chat request to the right model+provider.

        Args:
            messages: OpenAI-style message list.
            profile: Explicit profile name (auto/eco/premium/agentic).
            model: If set, may contain 'kani/<profile>' to select a profile,
                   or an explicit model ID to pass through.
            required_capabilities: Set of required capabilities (e.g., {'vision', 'tools', 'json_mode'}).

        Returns:
            A RoutingDecision with all the info needed to proxy the request.

        Raises:
            CapabilityNotSatisfiedError: When no model with required capabilities is available.
        """
        if required_capabilities is None:
            required_capabilities = set()
        # --- Resolve profile from model string if needed ---
        profile = self._resolve_profile(profile, model)

        profile_cfg = self.config.profiles.get(profile)
        if profile_cfg is None:
            log.warning(
                "Profile %r not found, falling back to %r",
                profile,
                self.config.default_profile,
            )
            profile = self.config.default_profile
            profile_cfg = self.config.profiles.get(profile)

        if profile_cfg is None:
            # Absolute fallback – shouldn't happen with a valid config
            raise ValueError(
                f"No profile configuration found for '{profile}' "
                f"and default profile '{self.config.default_profile}' is also missing."
            )

        # --- Extract prompt info from messages ---
        prompt, system_prompt = self._extract_prompts(messages)

        # --- Run scorer ---
        classification = self._classify(
            prompt, system_prompt, messages, profile=profile
        )

        tier: str = classification.get("tier") or _DEFAULT_TIER
        score: float = classification.get("score", 0.5)
        confidence: float = classification.get("confidence", 0.5)
        signals: list[str] = classification.get("signals", [])
        signal_details: dict[str, Any] | list[str] = classification.get(
            "signal_details", signals
        )
        agentic_score: float = classification.get("agentic_score", 0.0)

        # --- Override tier for agentic profile if agentic_score is high ---
        if profile == "agentic" and agentic_score > 0.6 and tier == "SIMPLE":
            tier = "MEDIUM"

        # --- Look up model in profile tier config with capability filtering ---
        resolved_tier, tier_cfg = self._resolve_tier_config(profile_cfg, tier)

        # Try to find capable model in current tier, escalate if needed
        primary_candidates = tier_cfg.resolve_primary_candidates()
        capable_candidates = self._filter_capable_candidates(
            primary_candidates, required_capabilities
        )

        # If no capable candidates in current tier, escalate to higher tiers
        if not capable_candidates and required_capabilities:
            current_tier = resolved_tier
            for tier_name in self._escalation_path(profile_cfg, current_tier):
                escalated_cfg = profile_cfg.tiers.get(tier_name)
                if escalated_cfg is None:
                    continue
                escalated_candidates = escalated_cfg.resolve_primary_candidates()
                capable_candidates = self._filter_capable_candidates(
                    escalated_candidates, required_capabilities
                )
                if capable_candidates:
                    resolved_tier = tier_name
                    tier_cfg = escalated_cfg
                    break

        # If still no capable candidates, raise error
        if not capable_candidates and required_capabilities:
            raise CapabilityNotSatisfiedError(required_capabilities)

        # --- Resolve primary model and provider ---
        primary_model, primary_provider = self._select_primary_candidate(
            profile,
            resolved_tier,
            tier_cfg,
            filter_to_candidates=capable_candidates if required_capabilities else None,
        )
        model_id = primary_model

        # Resolve provider name: entry override > tier default > config default
        provider_name = self._resolve_provider_name(primary_provider, tier_cfg.provider)

        provider_cfg = self._lookup_provider(provider_name)

        # --- Build fallback entries with capability filtering ---
        fallback_entries: list[FallbackEntry] = []
        fallback_candidates = tier_cfg.resolve_fallbacks()
        capable_fallbacks = self._filter_capable_candidates(
            fallback_candidates, required_capabilities
        )

        for fb_model, fb_provider in capable_fallbacks:
            fb_provider_name = self._resolve_provider_name(
                fb_provider, tier_cfg.provider
            )
            fb_provider_cfg = self._lookup_provider(fb_provider_name)
            fallback_entries.append(
                FallbackEntry(
                    model=fb_model,
                    provider=fb_provider_name,
                    base_url=fb_provider_cfg.base_url,
                    api_key=resolve_env(fb_provider_cfg.api_key),
                )
            )

        try:
            from kani.logger import RoutingLogger

            RoutingLogger.log_decision(
                prompt,
                tier=tier,
                score=score,
                confidence=confidence,
                signals=signal_details,
                agentic_score=agentic_score,
                model=model_id,
                provider=provider_name,
                profile=profile,
            )
        except Exception:
            log.exception("Failed to persist routing decision log")

        return RoutingDecision(
            model=model_id,
            provider=provider_name,
            base_url=provider_cfg.base_url,
            api_key=resolve_env(provider_cfg.api_key),
            tier=tier,
            score=score,
            confidence=confidence,
            signals=signals,
            agentic_score=agentic_score,
            profile=profile,
            fallbacks=fallback_entries,
            required_capabilities=sorted(list(required_capabilities)),
        )

    def resolve_model(
        self,
        *,
        profile: str | None = None,
        tier: str = "SIMPLE",
    ) -> RoutingDecision:
        """Resolve a model for internal use without running scorer or logging.

        Used by compaction to find the summary model via the Router's
        profile/tier resolution path, skipping scorer classification and
        RoutingLogger so internal resolution is not polluted with routing logs.

        Args:
            profile: Profile name, or None to use default_profile.
            tier: Tier name (SIMPLE, MEDIUM, COMPLEX, REASONING).

        Returns:
            A RoutingDecision with resolved model, base_url, api_key, provider,
            and fallbacks. score/confidence/signals are zero/empty as they are
            not applicable for internal resolution.
        """
        resolved_profile = profile or self.config.default_profile

        profile_cfg = self.config.profiles.get(resolved_profile)
        if profile_cfg is None:
            log.warning(
                "Profile %r not found, falling back to %r",
                resolved_profile,
                self.config.default_profile,
            )
            resolved_profile = self.config.default_profile
            profile_cfg = self.config.profiles.get(resolved_profile)

        if profile_cfg is None:
            raise ValueError(
                f"No profile configuration found for '{resolved_profile}' "
                f"and default profile '{self.config.default_profile}' is also missing."
            )

        resolved_tier, tier_cfg = self._resolve_tier_config(profile_cfg, tier)

        primary_model, primary_provider = self._select_primary_candidate(
            resolved_profile,
            resolved_tier,
            tier_cfg,
        )
        provider_name = self._resolve_provider_name(primary_provider, tier_cfg.provider)
        provider_cfg = self._lookup_provider(provider_name)

        fallback_entries: list[FallbackEntry] = []
        for fb_model, fb_provider in tier_cfg.resolve_fallbacks():
            fb_provider_name = self._resolve_provider_name(
                fb_provider, tier_cfg.provider
            )
            fb_provider_cfg = self._lookup_provider(fb_provider_name)
            fallback_entries.append(
                FallbackEntry(
                    model=fb_model,
                    provider=fb_provider_name,
                    base_url=fb_provider_cfg.base_url,
                    api_key=resolve_env(fb_provider_cfg.api_key),
                )
            )

        return RoutingDecision(
            model=primary_model,
            provider=provider_name,
            base_url=provider_cfg.base_url,
            api_key=resolve_env(provider_cfg.api_key),
            tier=tier,
            score=0.0,
            confidence=0.0,
            signals=[],
            agentic_score=0.0,
            profile=resolved_profile,
            fallbacks=fallback_entries,
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _get_model_capabilities(self, model_id: str) -> set[str]:
        """Get capabilities for a model using prefix matching from config.

        Returns:
            Set of capability strings (e.g., {'vision', 'tools', 'json_mode'}).
            Empty set if model not found in config.
        """
        for entry in self.config.model_capabilities:
            if model_id.startswith(entry.prefix):
                return set(entry.capabilities)
        return set()

    def _filter_capable_candidates(
        self,
        candidates: list[tuple[str, str]],
        required_capabilities: set[str],
    ) -> list[tuple[str, str]]:
        """Filter candidates to those that have all required capabilities.

        Args:
            candidates: List of (model_id, provider_name) tuples.
            required_capabilities: Set of required capability strings.

        Returns:
            Filtered list of candidates with all required capabilities.
            Returns all candidates if no capabilities are required.
        """
        if not required_capabilities:
            return candidates

        capable = []
        for model_id, provider_name in candidates:
            model_caps = self._get_model_capabilities(model_id)
            if required_capabilities.issubset(model_caps):
                capable.append((model_id, provider_name))

        return capable

    def _resolve_tier_config(self, profile_cfg: Any, tier: str) -> tuple[str, Any]:
        """Resolve a tier config, falling back to adjacent tiers if needed."""
        tier_cfg = profile_cfg.tiers.get(tier)
        if tier_cfg is not None:
            return tier, tier_cfg

        fallback_tier = self._fallback_tier_name(profile_cfg, tier)
        if fallback_tier is None:
            raise ValueError(f"No tier config for '{tier}'")
        return fallback_tier, profile_cfg.tiers[fallback_tier]

    def _escalation_path(self, profile_cfg: Any, current_tier: str) -> list[str]:
        """Generate escalation path from current tier to higher tiers.

        Searches upward in _TIER_ORDER, skipping the current tier.
        """
        try:
            idx = _TIER_ORDER.index(current_tier)
        except ValueError:
            idx = 1  # MEDIUM

        path = []
        for offset in range(1, len(_TIER_ORDER)):
            candidate_idx = idx + offset
            if 0 <= candidate_idx < len(_TIER_ORDER):
                candidate = _TIER_ORDER[candidate_idx]
                if candidate in profile_cfg.tiers:
                    path.append(candidate)
        return path

    def _select_primary_candidate(
        self,
        profile: str,
        tier: str,
        tier_cfg: Any,
        filter_to_candidates: list[tuple[str, str]] | None = None,
    ) -> tuple[str, str]:
        """Select a primary candidate via per profile+tier round-robin.

        Args:
            profile: Profile name.
            tier: Tier name.
            tier_cfg: Tier config.
            filter_to_candidates: If provided, select only from this list.
                                 Otherwise use all primary candidates.

        Returns:
            Selected (model_id, provider_name) tuple.
        """
        if filter_to_candidates is not None:
            candidates = filter_to_candidates
        else:
            candidates = tier_cfg.resolve_primary_candidates()

        if len(candidates) == 1:
            return candidates[0]

        state_key = (profile, tier)
        with self._rr_lock:
            next_idx = self._rr_state.get(state_key, 0)
            selected_idx = next_idx % len(candidates)
            self._rr_state[state_key] = (selected_idx + 1) % len(candidates)

        selected = candidates[selected_idx]
        log.debug(
            "Primary round-robin selected profile=%s tier=%s index=%d/%d model=%s provider=%s",
            profile,
            tier,
            selected_idx,
            len(candidates),
            selected[0],
            selected[1] or "",
        )
        return selected

    def _resolve_provider_name(self, entry_provider: str, tier_provider: str) -> str:
        """Resolve provider name: entry override > tier default > config default."""
        if entry_provider:
            return entry_provider
        if tier_provider and tier_provider != "default":
            return tier_provider
        return self.config.default_provider

    def _lookup_provider(self, provider_name: str) -> ProviderConfig:
        """Look up a ProviderConfig by name, falling back to default."""
        provider_cfg = self.config.providers.get(provider_name)
        if provider_cfg is None:
            # Try default provider
            provider_cfg = self.config.providers.get(self.config.default_provider)
        if provider_cfg is None:
            raise ValueError(f"Provider '{provider_name}' not found in config")
        return provider_cfg

    def _resolve_profile(self, profile: str | None, model: str | None) -> str:
        """Determine the profile name from explicit arg or model string."""
        if profile:
            return profile

        if model and model.startswith("kani/"):
            return model.removeprefix("kani/")

        return self.config.default_profile

    @staticmethod
    def _extract_prompts(messages: list[dict[str, Any]]) -> tuple[str, str]:
        """Pull the last user message and system prompt from a message list."""
        prompt = ""
        system_prompt = ""

        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if isinstance(content, list):
                # Handle multimodal content blocks – extract text parts
                content = " ".join(
                    part.get("text", "")
                    for part in content
                    if isinstance(part, dict) and part.get("type") == "text"
                )
            if role == "system":
                system_prompt = str(content)

        # Last user message
        for msg in reversed(messages):
            if msg.get("role") == "user":
                content = msg.get("content", "")
                if isinstance(content, list):
                    content = " ".join(
                        part.get("text", "")
                        for part in content
                        if isinstance(part, dict) and part.get("type") == "text"
                    )
                prompt = str(content)
                break

        return prompt, system_prompt

    def _classify(
        self,
        prompt: str,
        system_prompt: str,
        messages: list[dict[str, Any]],
        *,
        profile: str,
    ) -> dict[str, Any]:
        """Run the scorer to classify the prompt complexity.

        Returns a dict with keys: score, tier, confidence, signals, agentic_score.
        Falls back conservatively if the scorer module isn't available.
        """
        _ = system_prompt, messages

        try:
            from kani.scorer import AgenticClassifier, LLMClassifier, Scorer

            llm_clf = None
            agentic_clf = None
            if self.config.llm_classifier:
                llm_clf = LLMClassifier(
                    model=self.config.llm_classifier.model,
                    base_url=self.config.llm_classifier.base_url,
                    api_key=self.config.llm_classifier.api_key,
                )
                if profile == "agentic":
                    agentic_clf = AgenticClassifier(
                        model=self.config.llm_classifier.model,
                        base_url=self.config.llm_classifier.base_url,
                        api_key=self.config.llm_classifier.api_key,
                    )
            elif profile == "agentic":
                agentic_clf = AgenticClassifier()

            scorer = Scorer(
                llm_classifier=llm_clf,
                agentic_classifier=agentic_clf,
                enable_routing_log=False,
            )
            result = scorer.classify(prompt, classify_agentic=(profile == "agentic"))
            tier_val = result.tier
            if hasattr(tier_val, "value"):
                tier_val = tier_val.value
            signal_details = result.signals
            signals = signal_details
            if isinstance(signal_details, dict):
                signals = [
                    k
                    for k, v in signal_details.items()
                    if v and isinstance(v, dict) and v.get("raw", 0) != 0
                ]
            return {
                "score": result.score,
                "tier": str(tier_val) if tier_val else None,
                "confidence": result.confidence,
                "signals": signals,
                "signal_details": signal_details,
                "agentic_score": result.agentic_score,
            }
        except ImportError:
            log.warning("Scorer module not available, using conservative default")
            return self._default_classify()

    @staticmethod
    def _default_classify() -> dict[str, Any]:
        """Conservative fallback when the scorer is unavailable."""
        return {
            "score": 0.0,
            "tier": _DEFAULT_TIER,
            "confidence": 0.35,
            "signals": ["scorer_unavailable"],
            "agentic_score": 0.0,
        }

    @staticmethod
    def _fallback_tier_name(profile_cfg: Any, tier: str) -> str | None:
        """Try adjacent tiers and return fallback tier name."""
        try:
            idx = _TIER_ORDER.index(tier)
        except ValueError:
            idx = 1  # MEDIUM

        # Search downward first, then upward
        for offset in range(1, len(_TIER_ORDER)):
            for direction in (-1, 1):
                candidate_idx = idx + direction * offset
                if 0 <= candidate_idx < len(_TIER_ORDER):
                    candidate = _TIER_ORDER[candidate_idx]
                    if candidate in profile_cfg.tiers:
                        return candidate
        return None

    @classmethod
    def _fallback_tier(cls, profile_cfg: Any, tier: str) -> Any:
        """Try adjacent tiers if the exact tier is missing from the profile."""
        fallback_tier = cls._fallback_tier_name(profile_cfg, tier)
        if fallback_tier is None:
            return None
        return profile_cfg.tiers[fallback_tier]
