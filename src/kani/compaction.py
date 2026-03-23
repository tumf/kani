"""Smart-proxy context compaction — Phase A (sync) and Phase B (background).

Phase A: compact oversized message histories before proxying upstream.
Phase B: background precompaction so cached summaries can be reused later.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("kani.compaction")


# ── Result types ──────────────────────────────────────────────────────────────


@dataclass
class CompactionResult:
    """Outcome of an attempt to compact a message list."""

    applied: bool = False
    messages: list[dict[str, Any]] = field(default_factory=list)
    mode: str = "off"  # off | skipped | inline | cached | failed
    session_id: str = ""
    session_mode: str = ""  # explicit | derived
    estimated_tokens_saved: int = 0
    error: str = ""


# ── Token estimation ──────────────────────────────────────────────────────────

_CHARS_PER_TOKEN = 4  # conservative estimate when no exact count is available


def _estimate_tokens(messages: list[dict[str, Any]]) -> int:
    """Rough token estimate for a message list (chars / 4)."""
    total_chars = sum(len(str(m.get("content", ""))) for m in messages)
    return max(1, total_chars // _CHARS_PER_TOKEN)


# ── Message compaction algorithm ──────────────────────────────────────────────


def _compact_messages(
    messages: list[dict[str, Any]],
    summary_text: str,
    protect_first_n: int,
    protect_last_n: int,
) -> list[dict[str, Any]] | None:
    """Replace the middle region with a summary message.

    Returns the compacted list, or None if safe compaction is not possible.

    Rules:
    - protect the first protect_first_n and last protect_last_n messages
    - the middle region must have at least 1 message to replace
    - a system message at position 0 is always preserved in addition to head guard
    - result must maintain valid role ordering (system → user/assistant alternation)
    """
    n = len(messages)
    if n < 3:
        return None  # not enough messages to compact

    # Always preserve a leading system message
    has_system = messages[0].get("role") == "system"
    head_end = protect_first_n + (1 if has_system else 0)

    tail_start = n - protect_last_n

    if tail_start <= head_end:
        return None  # protected regions overlap — nothing to compact

    middle = messages[head_end:tail_start]
    if not middle:
        return None

    # Use "system" role for the summary so it never conflicts with head/tail
    # role ordering — system messages are not subject to the
    # user/assistant alternation requirement.
    summary_msg = {
        "role": "system",
        "content": (
            f"[Context summary — earlier conversation compressed by proxy]\n{summary_text}"
        ),
    }
    compacted = list(messages[:head_end]) + [summary_msg] + list(messages[tail_start:])

    # Validate that the tail doesn't start with two consecutive same-role messages
    # (ignoring the system summary which acts as a natural context separator).
    tail_messages = list(messages[tail_start:])
    if len(tail_messages) >= 2:
        roles = [m.get("role") for m in tail_messages if m.get("role") != "system"]
        for i in range(len(roles) - 1):
            if roles[i] == roles[i + 1]:
                return None

    return compacted


# ── Synchronous (Phase A) compaction ─────────────────────────────────────────


def try_sync_compaction(
    messages: list[dict[str, Any]],
    summary_text: str,
    protect_first_n: int,
    protect_last_n: int,
    original_tokens: int,
) -> tuple[list[dict[str, Any]] | None, int]:
    """Attempt synchronous compaction.

    Returns (compacted_messages_or_None, estimated_tokens_saved).
    """
    compacted = _compact_messages(
        messages, summary_text, protect_first_n, protect_last_n
    )
    if compacted is None:
        return None, 0
    new_tokens = _estimate_tokens(compacted)
    saved = max(0, original_tokens - new_tokens)
    return compacted, saved


# ── Summary generation (shared by Phase A and Phase B) ───────────────────────


async def generate_summary(
    messages: list[dict[str, Any]],
    *,
    summary_model: str,
    base_url: str,
    api_key: str,
    protect_first_n: int,
    protect_last_n: int,
) -> str:
    """Call an LLM to generate a handoff summary of the middle message region.

    Returns the summary text, or raises on failure.
    """
    import httpx

    n = len(messages)
    has_system = messages[0].get("role") == "system" if messages else False
    head_end = protect_first_n + (1 if has_system else 0)
    tail_start = n - protect_last_n
    middle = messages[head_end:tail_start] if tail_start > head_end else messages

    conversation_text = "\n".join(
        f"{m.get('role', 'unknown').upper()}: {m.get('content', '')}"
        for m in middle
    )
    prompt = (
        "You are a context compaction assistant. Produce a concise factual handoff "
        "summary of the conversation below. The summary will replace these messages "
        "so the next assistant turn can continue seamlessly. Include key decisions, "
        "facts, constraints, and progress. Be direct and dense.\n\n"
        f"{conversation_text}"
    )

    url = base_url.rstrip("/")
    if not url.endswith("/v1"):
        url += "/v1"
    url += "/chat/completions"

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    payload = {
        "model": summary_model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 512,
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()

    choices = data.get("choices", [])
    if not choices:
        raise ValueError("No choices in summary response")
    return choices[0]["message"]["content"].strip()


# ── Background precompaction worker (Phase B) ─────────────────────────────────


class BackgroundCompactionWorker:
    """In-process async worker for background precompaction jobs."""

    def __init__(self, max_concurrency: int = 2) -> None:
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._tasks: set[asyncio.Task] = set()  # type: ignore[type-arg]

    def schedule(
        self,
        summary_id: str,
        session_id: str,
        snap_hash: str,
        messages: list[dict[str, Any]],
        *,
        summary_model: str,
        base_url: str,
        api_key: str,
        protect_first_n: int,
        protect_last_n: int,
        original_tokens: int,
    ) -> None:
        """Schedule a background compaction job (non-blocking)."""
        task = asyncio.create_task(
            self._run(
                summary_id,
                session_id,
                snap_hash,
                messages,
                summary_model=summary_model,
                base_url=base_url,
                api_key=api_key,
                protect_first_n=protect_first_n,
                protect_last_n=protect_last_n,
                original_tokens=original_tokens,
            )
        )
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _run(
        self,
        summary_id: str,
        session_id: str,
        snap_hash: str,
        messages: list[dict[str, Any]],
        *,
        summary_model: str,
        base_url: str,
        api_key: str,
        protect_first_n: int,
        protect_last_n: int,
        original_tokens: int,
    ) -> None:
        from kani.compaction_store import update_summary

        async with self._semaphore:
            update_summary(summary_id, status="running")
            try:
                summary_text = await generate_summary(
                    messages,
                    summary_model=summary_model,
                    base_url=base_url,
                    api_key=api_key,
                    protect_first_n=protect_first_n,
                    protect_last_n=protect_last_n,
                )
                _, saved = try_sync_compaction(
                    messages,
                    summary_text,
                    protect_first_n,
                    protect_last_n,
                    original_tokens,
                )
                update_summary(
                    summary_id,
                    status="ready",
                    summary_text=summary_text,
                    estimated_tokens_saved=saved,
                )
                logger.info(
                    "COMPACTION_BG session=%s snap=%s saved_tokens=%d",
                    session_id,
                    snap_hash[:8],
                    saved,
                )
            except Exception as exc:
                update_summary(summary_id, status="failed", error_message=str(exc)[:512])
                logger.warning(
                    "COMPACTION_BG_FAILED session=%s snap=%s error=%s",
                    session_id,
                    snap_hash[:8],
                    exc,
                )

    async def shutdown(self) -> None:
        """Cancel and await all in-flight tasks."""
        for task in list(self._tasks):
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)


# ── Singleton worker (owned by proxy lifespan) ────────────────────────────────

_worker: BackgroundCompactionWorker | None = None


def get_worker() -> BackgroundCompactionWorker | None:
    return _worker


def set_worker(w: BackgroundCompactionWorker | None) -> None:
    global _worker
    _worker = w
