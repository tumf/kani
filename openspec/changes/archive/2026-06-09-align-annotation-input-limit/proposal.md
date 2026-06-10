---
change_type: implementation
priority: medium
dependencies: []
references:
  - https://github.com/tumf/kani/issues/3
  - src/kani/classification_context.py
  - src/kani/training_data.py
---

# Align Annotation Input Limit

**Change Type**: implementation

## Problem / Context

Runtime routing classification builds a bounded classification input with a default maximum currently set to 3500 characters. Offline annotation currently truncates prompts at a smaller limit before sending them to the annotator. This mismatch can create labels based on a different input slice than runtime routing sees.

## Proposed Solution

Align offline annotator prompt truncation with the runtime classification input default maximum. The limit must be shared with, imported from, or derived from a named runtime classification input default constant so future runtime default changes cannot silently leave annotation at the old value.

## Acceptance Criteria

1. Offline annotation uses the runtime classification input default maximum by default, currently 3500 characters.
2. The limit is shared with, imported from, or derived from a named runtime classification input default constant.
3. Tests prove prompts longer than 2000 characters are not prematurely truncated at 2000.
4. Tests prove prompts are still bounded at the runtime classification input default maximum.
5. Runtime routing and proxy behavior are unchanged.

## Explicit Completion Conditions

- `src/kani/training_data.py` no longer hardcodes a 2000-character annotation truncation limit.
- The runtime classification default maximum is represented by a shared/importable constant or equivalent single source of truth used by offline annotation.
- Unit tests inspect the annotator request payload and fail if the prompt is truncated to 2000 or exceeds the runtime classification input default maximum.
- Relevant local verification commands complete successfully for training-data tests and Python checks.

## Out of Scope

- Making annotation limit user-configurable.
- Rebuilding or shipping classifier artifacts.
- Changing runtime classification context selection rules beyond keeping the known limit aligned.
