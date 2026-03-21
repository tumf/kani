# AGENTS.md

This file is for coding agents working in `kani`.

## Project Snapshot

- Language: Python 3.13+
- Package manager and task runner: `uv`
- Build backend: `uv_build`
- CLI entrypoint: `kani = "kani.cli:main"`
- App shape: Click CLI + FastAPI proxy + Pydantic config/models
- Source tree: `src/kani/`
- Tests: `tests/` with `pytest`
- Type checking: `pyright`
- Lint/format: `ruff`

## Repository Layout

- `src/kani/cli.py` - Click commands for `serve`, `route`, and `config`
- `src/kani/proxy.py` - FastAPI OpenAI-compatible proxy
- `src/kani/router.py` - routing decisions and provider/profile selection
- `src/kani/scorer.py` - prompt classification logic and LLM escalation
- `src/kani/config.py` - YAML config loading and env-var resolution
- `src/kani/logger.py` - JSONL routing log writer
- `src/kani/dirs.py` - XDG/platformdirs helpers
- `tests/test_scorer.py` - scorer behavior coverage
- `tests/test_llm_classifier.py` - LLM classifier and logging coverage
- `config.yaml` - example/default local configuration

## Setup Commands

- Install runtime + dev dependencies: `uv sync --dev`
- Install runtime dependencies only: `uv sync`
- Run the CLI locally: `uv run kani --help`
- Start the proxy locally: `uv run kani serve`
- Route a prompt locally: `uv run kani route "hello world"`
- Show resolved config: `uv run kani config`

## Build, Lint, Format, Typecheck, Test

- Build package artifacts: `uv build`
- Lint source: `uv run ruff check src/`
- Check formatting: `uv run ruff format --check src/ tests/`
- Auto-format source and tests: `uv run ruff format src/ tests/`
- Type-check source: `uv run pyright src/`
- Run full test suite: `uv run pytest tests/ -q`

## Single-Test Commands

- Run one test file: `uv run pytest tests/test_scorer.py -q`
- Run one test class: `uv run pytest tests/test_scorer.py::TestReasoningPrompts -q`
- Run one test method: `uv run pytest tests/test_scorer.py::TestReasoningPrompts::test_prove_theorem -q`
- Run tests matching an expression: `uv run pytest tests/ -q -k reasoning`
- Stop after first failure: `uv run pytest tests/ -q -x`

## CI Expectations

The GitHub Actions workflow in `.github/workflows/ci.yml` effectively defines the acceptance bar:

- `uv sync --dev`
- `uv run ruff check src/`
- `uv run ruff format --check src/ tests/`
- `uv run pyright src/`
- `uv run pytest tests/ -q`
- `uv build`

If you change Python code, aim to run the relevant subset first, then the full suite if the change is broad.

## Rules Files

- No `.cursor/rules/` directory was found.
- No `.cursorrules` file was found.
- No `.github/copilot-instructions.md` file was found.

If any of those files are added later, treat them as higher-priority repository instructions and update this file.

## Coding Style

The codebase follows a straightforward typed Python style with light structure and minimal abstraction.

### Imports

- Use `from __future__ import annotations` in Python modules.
- Group imports as: standard library, third-party, local package imports.
- Prefer explicit imports over wildcard imports.
- Keep local imports inside functions only when avoiding import cycles or heavy startup cost.
- Use `TYPE_CHECKING` for type-only imports when helpful, as in `src/kani/logger.py`.

### Formatting

- Follow Ruff formatting; do not hand-format against the formatter.
- Use 4-space indentation.
- Keep line length formatter-friendly; long calls are wrapped vertically.
- Preserve the existing style of section dividers made from comment banners when editing long modules.
- Prefer concise docstrings on modules, classes, and non-obvious functions.

### Types

- Add type hints for public functions, methods, and important locals when clarity helps.
- Use modern Python unions like `str | None`, not `Optional[str]`.
- Prefer built-in generics like `list[str]`, `dict[str, Any]`, and `tuple[str, str]`.
- Use Pydantic `BaseModel` for structured config and API-facing data.
- Use dataclasses or enums only where they fit existing patterns; do not introduce new frameworks casually.
- Keep `Any` contained to boundaries like request payloads, YAML data, and flexible JSON structures.

### Naming

- Use `snake_case` for functions, methods, variables, and module names.
- Use `PascalCase` for classes and Pydantic models.
- Use `UPPER_SNAKE_CASE` for module-level constants such as `_DEFAULT_TIER` and `_TIER_ORDER`.
- Test classes use `Test...` naming; test methods use `test_...` naming.
- Prefer descriptive names over short abbreviations unless the abbreviation is already established in the file.

### Control Flow and Design

- Keep functions focused and direct; most modules prefer readable procedural logic over deep indirection.
- Match the current architecture: CLI -> config/router -> scorer/proxy helpers.
- Prefer small private helpers for repeated logic instead of clever abstractions.
- Preserve current public behavior and CLI/API shapes unless the task explicitly changes them.
- Avoid introducing unnecessary dependencies.

### Error Handling

- Fail loudly for invalid internal configuration with `ValueError` or assertions where the code already does that.
- At HTTP boundaries, return structured OpenAI-style JSON errors rather than raw exceptions.
- Catch narrow exceptions when possible, but match existing patterns at network and file I/O boundaries.
- Log operational failures with the standard `logging` module.
- For optional integrations, degrade gracefully instead of crashing; `router.py` and `logger.py` already follow this pattern.

### Config and Secrets

- Keep secrets in environment variables via `${VAR}` placeholders in YAML; do not hardcode credentials in code.
- Preserve config precedence rules: explicit path, `KANI_CONFIG`, local config, XDG config, then `/etc`.
- When changing config models, update both validation code and docs/examples if needed.

### FastAPI and CLI Conventions

- Keep FastAPI handlers thin; route complex logic into helpers or domain classes.
- Preserve OpenAI-compatible request/response shapes.
- Keep Click commands simple and explicit.
- Prefer JSON-serializable return structures and Pydantic `.model_dump()` where already used.

### Testing Conventions

- Put tests under `tests/`.
- Prefer `pytest` style with plain `assert` statements.
- Group related tests into `Test...` classes.
- Use `unittest.mock.MagicMock` and `patch` for network-bound or external behavior.
- Cover both success paths and graceful fallbacks.
- When adding logic to scoring or routing, add tests for thresholds, edge cases, and fallback behavior.

## Agent Advice

- Read the surrounding module before editing; several files use repeated patterns worth preserving.
- Check whether a change affects CLI behavior, config loading, routing behavior, and tests together.
- If you modify API behavior or config semantics, update `README.md` and possibly `CONTRIBUTING.md`.
- Prefer minimal diffs that fit the current code style.
- Before finishing a meaningful Python change, run lint, format check, typecheck, and the most relevant tests.

## Safe Defaults for Agents

- Assume `uv` is the canonical way to run all project commands.
- Assume `src/kani/` is the authoritative source tree.
- Assume CI compatibility matters more than local convenience.
- Assume user changes elsewhere in the worktree are intentional; do not revert unrelated edits.
