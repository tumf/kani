"""Kani smart router – maps incoming messages to the best model+provider."""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field

from kani.config import KaniConfig, ProviderConfig, resolve_env

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Routing result
# ---------------------------------------------------------------------------

class RoutingDecision(BaseModel):
    """The outcome of a routing decision."""
    model: str
    provider: str
    base_url: str
    api_key: str = ''
    tier: str
    score: float
    confidence: float
    signals: list[str] = Field(default_factory=list)
    agentic_score: float = 0.0


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

# Default tier when the scorer can't decide
_DEFAULT_TIER = 'MEDIUM'

# Ordered tiers from simplest to most complex
_TIER_ORDER = ['SIMPLE', 'MEDIUM', 'COMPLEX', 'REASONING']


class Router:
    """Given chat messages, decides which model and provider to use."""

    def __init__(self, config: KaniConfig) -> None:
        self.config = config

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def route(
        self,
        messages: list[dict[str, Any]],
        *,
        profile: str | None = None,
        model: str | None = None,
    ) -> RoutingDecision:
        """Route a chat request to the right model+provider.

        Args:
            messages: OpenAI-style message list.
            profile: Explicit profile name (auto/eco/premium/agentic).
            model: If set, may contain 'kani/<profile>' to select a profile,
                   or an explicit model ID to pass through.

        Returns:
            A RoutingDecision with all the info needed to proxy the request.
        """
        # --- Resolve profile from model string if needed ---
        profile = self._resolve_profile(profile, model)

        profile_cfg = self.config.profiles.get(profile)
        if profile_cfg is None:
            log.warning("Profile %r not found, falling back to %r", profile, self.config.default_profile)
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
        classification = self._classify(prompt, system_prompt, messages)

        tier: str = classification.get('tier') or _DEFAULT_TIER
        score: float = classification.get('score', 0.5)
        confidence: float = classification.get('confidence', 0.5)
        signals: list[str] = classification.get('signals', [])
        agentic_score: float = classification.get('agentic_score', 0.0)

        # --- Override tier for agentic profile if agentic_score is high ---
        if profile == 'agentic' and agentic_score > 0.6 and tier == 'SIMPLE':
            tier = 'MEDIUM'

        # --- Look up model in profile tier config ---
        tier_cfg = profile_cfg.tiers.get(tier)
        if tier_cfg is None:
            # Fall back through tiers
            tier_cfg = self._fallback_tier(profile_cfg, tier)
            if tier_cfg is None:
                raise ValueError(f"No tier config for '{tier}' in profile '{profile}'")

        model_id = tier_cfg.primary

        # --- Resolve provider ---
        provider_name = tier_cfg.provider
        if provider_name == 'default':
            provider_name = self.config.default_provider

        provider_cfg = self.config.providers.get(provider_name)
        if provider_cfg is None:
            # Try default provider
            provider_cfg = self.config.providers.get(self.config.default_provider)
        if provider_cfg is None:
            raise ValueError(f"Provider '{provider_name}' not found in config")

        # --- Resolve env vars in api_key ---
        api_key = resolve_env(provider_cfg.api_key)

        return RoutingDecision(
            model=model_id,
            provider=provider_name,
            base_url=provider_cfg.base_url,
            api_key=api_key,
            tier=tier,
            score=score,
            confidence=confidence,
            signals=signals,
            agentic_score=agentic_score,
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _resolve_profile(self, profile: str | None, model: str | None) -> str:
        """Determine the profile name from explicit arg or model string."""
        if profile:
            return profile

        if model and model.startswith('kani/'):
            return model.removeprefix('kani/')

        return self.config.default_profile

    @staticmethod
    def _extract_prompts(messages: list[dict[str, Any]]) -> tuple[str, str]:
        """Pull the last user message and system prompt from a message list."""
        prompt = ''
        system_prompt = ''

        for msg in messages:
            role = msg.get('role', '')
            content = msg.get('content', '')
            if isinstance(content, list):
                # Handle multimodal content blocks – extract text parts
                content = ' '.join(
                    part.get('text', '') for part in content
                    if isinstance(part, dict) and part.get('type') == 'text'
                )
            if role == 'system':
                system_prompt = str(content)

        # Last user message
        for msg in reversed(messages):
            if msg.get('role') == 'user':
                content = msg.get('content', '')
                if isinstance(content, list):
                    content = ' '.join(
                        part.get('text', '') for part in content
                        if isinstance(part, dict) and part.get('type') == 'text'
                    )
                prompt = str(content)
                break

        return prompt, system_prompt

    def _classify(
        self,
        prompt: str,
        system_prompt: str,
        messages: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Run the scorer to classify the prompt complexity.

        Returns a dict with keys: score, tier, confidence, signals, agentic_score.
        Falls back gracefully if the scorer module isn't available yet.
        """
        # Rough token estimate (4 chars per token)
        estimated_tokens = sum(
            len(str(m.get('content', ''))) for m in messages
        ) // 4

        try:
            from kani.scorer import Scorer

            scorer = Scorer()
            result = scorer.classify(prompt)
            tier_val = result.tier
            # Tier may be an enum or string
            if hasattr(tier_val, 'value'):
                tier_val = tier_val.value
            # signals may be a dict or list — only include non-zero dimensions
            signals = result.signals
            if isinstance(signals, dict):
                signals = [
                    k for k, v in signals.items()
                    if v and isinstance(v, dict) and v.get('raw', 0) != 0
                ]
            return {
                'score': result.score,
                'tier': str(tier_val) if tier_val else None,
                'confidence': result.confidence,
                'signals': signals,
                'agentic_score': result.agentic_score,
            }
        except ImportError:
            log.warning("Scorer module not available, using heuristic fallback")
            return self._heuristic_classify(prompt, system_prompt, estimated_tokens)

    @staticmethod
    def _heuristic_classify(
        prompt: str,
        system_prompt: str,
        estimated_tokens: int,
    ) -> dict[str, Any]:
        """Basic heuristic scorer when the real scorer isn't available."""
        signals: list[str] = []
        score = 0.3
        agentic_score = 0.0

        prompt_lower = prompt.lower()
        length = len(prompt)

        # Length signals
        if length < 60:
            signals.append('short_prompt')
        elif length > 800:
            signals.append('long_prompt')
            score += 0.2

        # Code signals
        code_keywords = ['```', 'def ', 'class ', 'import ', 'function ', 'const ', 'async ']
        if any(kw in prompt for kw in code_keywords):
            signals.append('code_content')
            score += 0.15

        # Reasoning signals
        reasoning_words = ['explain', 'analyze', 'compare', 'evaluate', 'prove', 'derive', 'why']
        if any(w in prompt_lower for w in reasoning_words):
            signals.append('reasoning_request')
            score += 0.15

        # Agentic signals
        agentic_words = ['search', 'browse', 'execute', 'run', 'call', 'fetch', 'tool', 'action']
        agentic_hits = sum(1 for w in agentic_words if w in prompt_lower)
        if agentic_hits > 0:
            signals.append('agentic_language')
            agentic_score = min(1.0, agentic_hits * 0.25)

        # System prompt complexity
        if len(system_prompt) > 500:
            signals.append('complex_system_prompt')
            score += 0.1

        # Token volume
        if estimated_tokens > 2000:
            signals.append('high_token_count')
            score += 0.1

        score = min(1.0, score)

        # Map score to tier
        if score < 0.3:
            tier = 'SIMPLE'
        elif score < 0.55:
            tier = 'MEDIUM'
        elif score < 0.8:
            tier = 'COMPLEX'
        else:
            tier = 'REASONING'

        return {
            'score': round(score, 3),
            'tier': tier,
            'confidence': 0.4,  # heuristic = low confidence
            'signals': signals,
            'agentic_score': round(agentic_score, 3),
        }

    @staticmethod
    def _fallback_tier(profile_cfg: Any, tier: str) -> Any:
        """Try adjacent tiers if the exact tier is missing from the profile."""
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
                        return profile_cfg.tiers[candidate]
        return None
