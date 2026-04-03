"""Build bounded, deterministic classification text from chat messages."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

_SHORT_FOLLOWUP_PHRASES = {
    "ok",
    "okay",
    "yes",
    "yeah",
    "sure",
    "continue",
    "go on",
    "sounds good",
    "はい",
    "うん",
    "了解",
    "続けて",
    "その方針で",
    "それで",
}


@dataclass(frozen=True)
class ClassificationInput:
    """Normalized classification input derived from conversation context."""

    text: str
    last_user_message: str
    system_prompt: str
    selected_turn_count: int
    selected_user_turn_count: int
    selected_assistant_turn_count: int
    truncated: bool
    last_user_is_short_followup: bool


@dataclass(frozen=True)
class _NormalizedTurn:
    idx: int
    role: str
    text: str


def _normalize_content(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()

    if isinstance(content, list):
        text_chunks: list[str] = []
        for part in content:
            if not isinstance(part, dict):
                continue
            if part.get("type") != "text":
                continue
            text = str(part.get("text", "")).strip()
            if text:
                text_chunks.append(text)
        return "\n".join(text_chunks).strip()

    return ""


def _is_short_followup(text: str) -> bool:
    normalized = text.strip().lower()
    if not normalized:
        return False

    if normalized in _SHORT_FOLLOWUP_PHRASES:
        return True

    if len(normalized) <= 8 and len(normalized.split()) <= 3:
        return True

    return False


def build_classification_input(
    messages: list[dict[str, Any]],
    *,
    max_context_turns: int = 8,
    max_user_turns: int = 4,
    max_assistant_turns: int = 2,
    max_chars: int = 3500,
) -> ClassificationInput:
    """Build deterministic classification text from conversation context."""

    latest_system = ""
    turns: list[_NormalizedTurn] = []

    for idx, message in enumerate(messages):
        role = str(message.get("role", "")).strip().lower()
        if role not in {"system", "user", "assistant"}:
            continue

        text = _normalize_content(message.get("content", ""))
        if not text:
            continue

        if role == "system":
            latest_system = text
            continue

        turns.append(_NormalizedTurn(idx=idx, role=role, text=text))

    last_user_message = ""
    last_user_turn_index = -1
    for i in range(len(turns) - 1, -1, -1):
        if turns[i].role == "user":
            last_user_message = turns[i].text
            last_user_turn_index = i
            break

    if last_user_turn_index == -1:
        fallback_text = latest_system or ""
        return ClassificationInput(
            text=fallback_text,
            last_user_message="",
            system_prompt=latest_system,
            selected_turn_count=0,
            selected_user_turn_count=0,
            selected_assistant_turn_count=0,
            truncated=False,
            last_user_is_short_followup=False,
        )

    selected: list[_NormalizedTurn] = []
    selected_user_turns = 0
    selected_assistant_turns = 0

    for turn in reversed(turns[: last_user_turn_index + 1]):
        if len(selected) >= max_context_turns:
            break

        if turn.role == "user":
            if selected_user_turns >= max_user_turns:
                break
            selected_user_turns += 1
            selected.append(turn)
            continue

        if selected_user_turns == 0:
            continue

        if selected_assistant_turns >= max_assistant_turns:
            continue

        selected_assistant_turns += 1
        selected.append(turn)

    selected.reverse()

    lines: list[str] = []
    if latest_system:
        lines.append("[system]")
        lines.append(latest_system)

    lines.append("[conversation]")
    for turn in selected:
        lines.append(f"{turn.role}: {turn.text}")

    classification_text = "\n".join(lines).strip()
    truncated = False
    if len(classification_text) > max_chars:
        truncated = True
        classification_text = classification_text[-max_chars:]

    return ClassificationInput(
        text=classification_text,
        last_user_message=last_user_message,
        system_prompt=latest_system,
        selected_turn_count=len(selected),
        selected_user_turn_count=selected_user_turns,
        selected_assistant_turn_count=selected_assistant_turns,
        truncated=truncated,
        last_user_is_short_followup=_is_short_followup(last_user_message),
    )
