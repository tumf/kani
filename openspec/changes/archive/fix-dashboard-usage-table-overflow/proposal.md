# Fix dashboard model-usage table overflow in 24h / 7d cards

## Premise / Context

- Kani dashboard is rendered as inline HTML from `src/kani/dashboard.py`.
- The "Actual model / provider usage" section has three cards: **24h**, **7d** (side-by-side), and **30d** (full-width via `span-full`).
- Each card renders a 7-column table (Model, Provider, Requests, Input, Output, Total, Avg latency) via `_render_model_usage_table()`.
- The table has `min-width: 560px`; card internal width can be as small as ~280px when two cards share a row (`minmax(320px, 1fr)` grid minus 40px padding).
- `.table-wrap` uses `overflow-x: auto`, producing a horizontal scrollbar whenever card width < table min-width.
- 30d card already uses `span-full` and does not exhibit the problem.

## Problem

The 24h and 7d model-usage cards are laid out side-by-side in a CSS grid, giving each card roughly half the container width. Because the inner 7-column table requires at least 560px but the card may be as narrow as ~280px internally, a horizontal scrollbar appears inside both cards on most screen widths. This makes the data harder to read and looks unpolished.

## Proposed Solution

Add the `span-full` CSS class to the 24h and 7d cards so they occupy the full grid width, matching the 30d card layout. This eliminates the width constraint that triggers the scrollbar.

**Single change in `src/kani/dashboard.py` lines 1332-1333:**

Before:
```python
f'            <div class="card"><h2>24h</h2>{_render_model_usage_table(...)}</div>',
f'            <div class="card"><h2>7d</h2>{_render_model_usage_table(...)}</div>',
```

After:
```python
f'            <div class="card span-full"><h2>24h</h2>{_render_model_usage_table(...)}</div>',
f'            <div class="card span-full"><h2>7d</h2>{_render_model_usage_table(...)}</div>',
```

## Acceptance Criteria

- The 24h and 7d model-usage cards each span the full grid width (no side-by-side layout).
- No horizontal scrollbar appears in the 24h or 7d cards at viewport widths >= 900px.
- The 30d card layout is unchanged.
- On mobile (< 900px), the media query `grid-column: auto` on `.card.span-full` keeps normal stacking behavior.
- Existing dashboard functionality is unaffected.
- Lint, format, typecheck, and tests pass.

## Out of Scope

- Reducing the number of table columns to fit a narrower layout.
- Responsive table redesign (e.g., card-based rows on mobile).
- Adding new tests for dashboard HTML rendering (no test infrastructure for visual layout exists).
