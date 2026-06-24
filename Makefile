.PHONY: test format format-check lint typecheck check install bump-patch bump-minor bump-major

test:
	uv run pytest tests/ -q

format:
	uv run ruff format src/ tests/

format-check:
	uv run ruff format --check src/ tests/

lint:
	uv run ruff check src/

typecheck:
	uv run pyright src/

check: format-check lint typecheck test

install:
	uv tool install --reinstall .

bump-patch:
	uvx bump-my-version bump patch

bump-minor:
	uvx bump-my-version bump minor

bump-major:
	uvx bump-my-version bump major
