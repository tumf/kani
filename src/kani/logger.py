"""Routing logger for kani classification decisions.

Logs every classification to a JSONL file for future training data collection.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from kani.scorer import ClassificationResult

log = logging.getLogger(__name__)


def _default_log_dir() -> Path:
    from kani.dirs import log_dir

    return log_dir()


_LOG_DIR = (
    Path(os.environ.get("KANI_LOG_DIR", ""))
    if os.environ.get("KANI_LOG_DIR")
    else _default_log_dir()
)
_write_lock = threading.Lock()


class RoutingLogger:
    """Logs every classification decision to a daily JSONL file.

    Thread-safe via a module-level lock. Uses sync append for simplicity.
    """

    _log_dir: Path = _LOG_DIR

    @classmethod
    def set_log_dir(cls, path: Path) -> None:
        """Override the log directory (useful for testing)."""
        cls._log_dir = path

    @classmethod
    def log_decision(
        cls,
        text: str,
        *,
        tier: str,
        score: float,
        confidence: float,
        signals: list[str] | dict[str, Any] | None = None,
        agentic_score: float = 0.0,
        model: str | None = None,
        provider: str | None = None,
        profile: str | None = None,
    ) -> None:
        """Append a routed decision record with resolved model/provider/profile."""
        try:
            cls._log_dir.mkdir(parents=True, exist_ok=True)
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            log_file = cls._log_dir / f"routing-{today}.jsonl"

            if isinstance(signals, dict):
                method = signals.get("method", {})
                method_str = (
                    method.get("raw", "unknown")
                    if isinstance(method, dict)
                    else str(method)
                )
                signal_payload = {k: v for k, v in signals.items() if k != "method"}
            else:
                method_str = "router"
                signal_payload = signals or []

            record: dict[str, Any] = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "prompt_preview": text[:200],
                "tier": tier,
                "score": score,
                "confidence": confidence,
                "method": method_str,
                "signals": signal_payload,
                "agentic_score": agentic_score,
                "model": model,
                "provider": provider,
                "profile": profile,
            }

            line = json.dumps(record, ensure_ascii=False) + "\n"
            with _write_lock:
                with open(log_file, "a", encoding="utf-8") as f:
                    f.write(line)
        except Exception as e:
            log.warning("Failed to write routing decision log: %s", e)

    @classmethod
    def log(cls, text: str, result: ClassificationResult) -> None:
        """Append a classification record to today's JSONL log file."""
        try:
            cls._log_dir.mkdir(parents=True, exist_ok=True)
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            log_file = cls._log_dir / f"routing-{today}.jsonl"

            method = result.signals.get("method", {})
            if isinstance(method, dict):
                method_str = method.get("raw", "unknown")
            else:
                method_str = str(method)

            record: dict[str, Any] = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "prompt_preview": text[:200],
                "tier": result.tier.value,
                "score": result.score,
                "confidence": result.confidence,
                "method": method_str,
                "signals": {k: v for k, v in result.signals.items() if k != "method"},
                "agentic_score": result.agentic_score,
            }

            line = json.dumps(record, ensure_ascii=False) + "\n"

            with _write_lock:
                with open(log_file, "a", encoding="utf-8") as f:
                    f.write(line)

        except Exception as e:
            log.warning("Failed to write routing log: %s", e)
