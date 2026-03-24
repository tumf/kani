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


# ── Incremental compaction helpers ────────────────────────────────────────────


def _compact_messages_incremental(
    messages: list[dict[str, Any]],
    prior_summary: str | None,
    prior_covered_count: int,
    new_delta_summary: str,
    protect_first_n: int,
    protect_last_n: int,
) -> tuple[list[dict[str, Any]] | None, int]:
    """Apply incremental compaction by merging prior and delta summaries via concatenation.

    Args:
        prior_summary: Summary text from the previous compaction cycle, or None (first pass).
        prior_covered_count: How many middle messages the prior summary already covers.
        new_delta_summary: Summary of the new (unsummarized) delta messages.
        protect_first_n: Messages to protect at the head.
        protect_last_n: Messages to protect at the tail.

    Returns:
        (compacted_messages, total_middle_count) on success, or (None, 0) on failure.
    """
    n = len(messages)
    if n < 1:
        return None, 0
    has_system = messages[0].get("role") == "system"
    head_end = protect_first_n + (1 if has_system else 0)
    tail_start = n - protect_last_n
    total_middle = max(0, tail_start - head_end)

    if prior_summary is not None:
        merged = f"{prior_summary}\n\n---\n\n[Continued]\n{new_delta_summary}"
    else:
        merged = new_delta_summary

    compacted = _compact_messages(messages, merged, protect_first_n, protect_last_n)
    if compacted is None:
        return None, 0
    return compacted, total_middle


async def _merge_summaries(
    prior: str,
    new_delta: str,
    merge_threshold: int,
    *,
    summary_model: str = "",
    base_url: str = "",
    api_key: str = "",
) -> str:
    """Merge prior and delta summaries.

    Uses concatenation when combined token estimate is below merge_threshold.
    Uses an LLM merge-summarize call when combined size meets or exceeds merge_threshold.
    Falls back to concatenation if LLM call fails or model/url is not configured.
    """
    combined_tokens = max(1, (len(prior) + len(new_delta)) // _CHARS_PER_TOKEN)

    if combined_tokens < merge_threshold or not summary_model or not base_url:
        return f"{prior}\n\n---\n\n[Continued]\n{new_delta}"

    import httpx

    prompt = (
        "You are a context compaction assistant. Below are two consecutive conversation "
        "summaries. Merge them into a single concise summary that preserves all key "
        "facts, decisions, constraints, and progress. Deduplicate overlapping content. "
        "Be direct and dense.\n\n"
        f"[Summary 1]\n{prior}\n\n[Summary 2]\n{new_delta}"
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

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        choices = data.get("choices", [])
        if choices:
            return choices[0]["message"]["content"].strip()
    except Exception:
        pass

    # Fallback to concatenation
    return f"{prior}\n\n---\n\n[Continued]\n{new_delta}"


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
        f"{m.get('role', 'unknown').upper()}: {m.get('content', '')}" for m in middle
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
        merge_threshold: int = 768,
        prior_summary: str | None = None,
        prior_covered_count: int = 0,
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
                merge_threshold=merge_threshold,
                prior_summary=prior_summary,
                prior_covered_count=prior_covered_count,
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
        merge_threshold: int = 768,
        prior_summary: str | None = None,
        prior_covered_count: int = 0,
    ) -> None:
        from kani.compaction_store import update_summary

        async with self._semaphore:
            update_summary(summary_id, status="running")
            try:
                n = len(messages)
                has_system = messages[0].get("role") == "system" if messages else False
                head_end = protect_first_n + (1 if has_system else 0)
                tail_start = n - protect_last_n

                if prior_summary is not None and prior_covered_count > 0:
                    # Incremental path: summarize only the delta
                    delta_messages = messages[
                        head_end + prior_covered_count : tail_start
                    ]
                    if not delta_messages:
                        # No new messages — reuse prior summary
                        summary_text = prior_summary
                        new_covered = prior_covered_count
                    else:
                        delta_summary = await generate_summary(
                            delta_messages + messages[tail_start:],
                            summary_model=summary_model,
                            base_url=base_url,
                            api_key=api_key,
                            protect_first_n=0,
                            protect_last_n=protect_last_n,
                        )
                        summary_text = await _merge_summaries(
                            prior_summary,
                            delta_summary,
                            merge_threshold,
                            summary_model=summary_model,
                            base_url=base_url,
                            api_key=api_key,
                        )
                        new_covered = max(0, tail_start - head_end)
                else:
                    # Full single-pass (no prior summary)
                    summary_text = await generate_summary(
                        messages,
                        summary_model=summary_model,
                        base_url=base_url,
                        api_key=api_key,
                        protect_first_n=protect_first_n,
                        protect_last_n=protect_last_n,
                    )
                    new_covered = max(0, tail_start - head_end)

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
                    covered_message_count=new_covered,
                )
                logger.info(
                    "COMPACTION_BG session=%s snap=%s saved_tokens=%d covered=%d",
                    session_id,
                    snap_hash[:8],
                    saved,
                    new_covered,
                )
            except Exception as exc:
                update_summary(
                    summary_id, status="failed", error_message=str(exc)[:512]
                )
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
