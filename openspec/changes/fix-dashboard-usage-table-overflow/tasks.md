## Implementation Tasks

- [ ] Task 1: Add `span-full` class to 24h and 7d model-usage cards (`src/kani/dashboard.py` lines 1332-1333). Change `<div class="card">` to `<div class="card span-full">` for both the 24h and 7d cards in the "Actual model / provider usage" section. (verification: `uv run ruff check src/` && `uv run ruff format --check src/ tests/` && `uv run pyright src/` && `uv run pytest tests/ -q`)

- [ ] Task 2: Visual verification. Start dev server with `uv run kani serve`, open `/dashboard`, confirm 24h and 7d cards are full-width with no horizontal scrollbar. (verification: manual browser check at various viewport widths)
