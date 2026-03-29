"""Process-local exponential backoff state for retryable fallback failures."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from threading import Lock

from kani.config import FallbackBackoffConfig

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BackoffStateEntry:
    """Snapshot of current backoff state for a model/provider pair."""

    failure_streak: int
    cooldown_until: datetime | None


class FallbackBackoffState:
    """Track retryable failure cooldowns keyed by model/provider."""

    def __init__(self, config: FallbackBackoffConfig) -> None:
        self._config = config
        self._entries: dict[tuple[str, str], BackoffStateEntry] = {}
        self._lock = Lock()

    def update_config(self, config: FallbackBackoffConfig) -> None:
        """Update runtime backoff tuning while preserving current entries."""
        with self._lock:
            self._config = config

    @property
    def enabled(self) -> bool:
        """Return whether cooldown tracking is enabled."""
        return self._config.enabled

    def is_in_cooldown(
        self,
        model: str,
        provider: str,
        *,
        now: datetime | None = None,
    ) -> bool:
        """Return True when the model/provider pair is still cooling down."""
        if not self.enabled:
            return False

        current = self.get_entry(model, provider)
        if current is None or current.cooldown_until is None:
            return False

        current_now = now or datetime.now(UTC)
        return current_now < current.cooldown_until

    def get_entry(self, model: str, provider: str) -> BackoffStateEntry | None:
        """Return the current state entry for a model/provider pair."""
        with self._lock:
            return self._entries.get((model, provider))

    def record_retryable_failure(
        self,
        model: str,
        provider: str,
        *,
        now: datetime | None = None,
    ) -> BackoffStateEntry:
        """Increment failure streak and apply a new cooldown window."""
        current_now = now or datetime.now(UTC)
        delay_seconds: float
        with self._lock:
            key = (model, provider)
            previous = self._entries.get(key)
            next_streak = 1 if previous is None else previous.failure_streak + 1
            delay_seconds = min(
                self._config.initial_delay_seconds
                * (self._config.multiplier ** (next_streak - 1)),
                self._config.max_delay_seconds,
            )
            entry = BackoffStateEntry(
                failure_streak=next_streak,
                cooldown_until=current_now + timedelta(seconds=delay_seconds),
            )
            self._entries[key] = entry

        logger.warning(
            "Fallback cooldown applied model=%s provider=%s streak=%d delay_seconds=%.3f cooldown_until=%s",
            model,
            provider,
            entry.failure_streak,
            delay_seconds,
            entry.cooldown_until.isoformat() if entry.cooldown_until else "",
        )
        return entry

    def record_success(self, model: str, provider: str) -> bool:
        """Reset failure streak after a successful request."""
        with self._lock:
            key = (model, provider)
            existing = self._entries.get(key)
            if existing is None:
                return False
            del self._entries[key]

        logger.info(
            "Fallback cooldown reset model=%s provider=%s previous_streak=%d",
            model,
            provider,
            existing.failure_streak,
        )
        return True
