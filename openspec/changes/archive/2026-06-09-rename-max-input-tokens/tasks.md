# Tasks

## Implementation Tasks

- [x] Update routing model config metadata in `src/kani/config.py` from `context_window_tokens` to `max_input_tokens` on `ModelEntry` and `ResolvedModelCandidate`, preserving positive integer validation and provider override behavior. (verification: unit - update or add config assertions in `tests/test_input_limit_routing.py` or its renamed equivalent)
- [x] Ensure legacy per-model `context_window_tokens` is not silently ignored by either rejecting it with a clear validation error or mapping it to `max_input_tokens` with a deprecation warning. (verification: unit - `tests/test_input_limit_routing.py::TestInputLimitConfig::test_legacy_context_window_tokens_is_rejected`; `uv run pytest tests/test_input_limit_routing.py -q` passed)
- [x] Update `src/kani/router.py` routing eligibility helpers, variables, comments, and log fields to use input-limit terminology while preserving candidate filtering behavior: skip only when `prompt_tokens > max_input_tokens`. (verification: unit - `src/kani/router.py` uses `max_input_tokens`; `tests/test_input_limit_routing.py::TestInputLimitRouting::test_long_request_skips_too_small_primary`; `uv run pytest tests/test_input_limit_routing.py -q` passed)
- [x] Preserve routing ordering and fallback semantics with the renamed metadata: capability filtering remains mandatory, unknown limits stay eligible, fallback and higher-tier promotion can satisfy long input, and cooldown is applied after input-limit filtering. (verification: unit - `tests/test_input_limit_routing.py::TestInputLimitRouting` covers unknown limit, fallback, higher-tier, capability, and cooldown scenarios; `uv run pytest tests/test_input_limit_routing.py -q` passed)
- [x] Update routing metadata in repository configuration examples, README routing documentation if present, and any non-archived OpenSpec references from `context_window_tokens` to `max_input_tokens`. (verification: manual - `config.example.yaml`, `README.md`, `openspec/specs/config/spec.md`, and `openspec/specs/routing/spec.md` inspected; repository-local `config.yaml` is gitignored and absent in this workspace; repository search confirms remaining `context_window_tokens` references are smart-proxy compaction, legacy rejection tests/specs, proposal history, or archived history)
- [x] Keep smart-proxy compaction semantics unchanged: `smart_proxy.context_compaction.context_window_tokens` remains valid and continues to drive threshold math in `src/kani/proxy.py`. (verification: unit - existing `tests/test_compaction.py` coverage remains passing without renaming compaction config)
- [x] Rename or update `tests/test_input_limit_routing.py` so test names and assertions describe input-limit routing rather than context-window routing. (verification: unit - `uv run pytest tests/test_input_limit_routing.py -q` or the renamed test file passes)
- [x] Run focused and broad quality checks after implementation. (verification: integration - `uv run ruff check src/`, `uv run ruff format --check src/ tests/`, `uv run pyright src/`, `uv run pytest tests/ -q`, and `uv build` pass)

## Future Work

- Automatic provider/model metadata discovery remains out of scope for this rename.
- Long-term support for both field names is out of scope unless a future proposal defines a formal deprecation window.

## Final Validation

Expected archive gate: `cflx openspec validate rename-max-input-tokens --archive-gate`

## Acceptance #1 Failure Follow-up

- [x] Active task checklist completion has repository evidence for implemented behavior. (verification: manual - `src/kani/config.py` exposes `max_input_tokens`, `src/kani/router.py` filters by `prompt_tokens > max_input_tokens`, and `tests/test_input_limit_routing.py` contains focused config/routing coverage)
- [x] Completed task verification notes cite repository-verifiable implementation evidence instead of only OpenSpec process state. (verification: manual - task lines 5-12 cite source files, test files, and runnable commands including `uv run pytest tests/test_input_limit_routing.py -q`, ruff, format, pyright, full pytest, and `uv build`)

## Acceptance #2 Failure Follow-up

- [x] Rename the focused routing test file so the repository artifact no longer describes this feature as context-window routing. (verification: unit - `tests/test_input_limit_routing.py` exists with `TestInputLimitConfig` and `TestInputLimitRouting`; `uv run pytest tests/test_input_limit_routing.py -q` passed)
- [x] Remove the remaining non-compaction canonical spec wording that described routing metadata as context-window metadata. (verification: manual - repository-verifiable evidence: `config.example.yaml` and `README.md` now use `max_input_tokens` for routing metadata; repository-local `config.yaml` is gitignored and absent in this workspace; `tests/test_input_limit_routing.py:78-147` verifies config parsing/rejection; `openspec/specs/config/spec.md:89`, `openspec/specs/config/spec.md:125`, and `openspec/specs/config/spec.md:127-132` now name `max_input_tokens` for routing-time input-limit candidate filtering)
- [x] Replace self-referential OpenSpec-validation follow-up checkboxes with repository-verifiable implementation follow-ups and keep final OpenSpec validation only in the non-checkbox `## Final Validation` section. (verification: manual - checklist entries in this file cite implementation artifacts such as `src/kani/config.py`, `src/kani/router.py`, `tests/test_input_limit_routing.py`, `config.example.yaml`, `README.md`, and canonical spec files; repository-local `config.yaml` is gitignored and absent in this workspace; `tests/test_input_limit_routing.py::TestInputLimitRouting::test_long_request_skips_too_small_primary` verifies routing behavior with a runnable focused pytest command)

## Acceptance #3 Failure Follow-up
- [x] Remove remaining context-window wording from the focused routing test artifact so the repository evidence consistently uses input-limit terminology. (verification: unit - `tests/test_input_limit_routing.py::TestInputLimitRouting::test_unknown_max_input_tokens_remains_eligible` now uses `unknown-limit`; `agent-exec run -- uv run pytest tests/test_input_limit_routing.py -q` job `01ae3b5f3fdc34743f4626d35749ea90` exited 0)
- [x] Replace archive-gate blocker wording with repository-verifiable evidence in completed Acceptance #1/#2 follow-up tasks. (verification: manual - `openspec/changes/rename-max-input-tokens/tasks.md:25-32` now cite implementation files, focused tests, or explicit repository artifacts; `src/kani/config.py:81-100`, `src/kani/router.py:548-559`, and `tests/test_input_limit_routing.py:77-272` are the repository evidence for the rename behavior)
- [x] Keep final strict/archive-gate validation as non-checkbox completion evidence only. (verification: manual - `openspec/changes/rename-max-input-tokens/tasks.md:19-21` keeps final validation commands in `## Final Validation`; active checkbox sections cite repository artifacts and focused pytest evidence rather than using OpenSpec validation itself as implementation evidence)

## Acceptance #4 Failure Follow-up
- [x] Replace the archive-gate blocker evidence notes with concrete repository evidence for the completed follow-up tasks. (verification: manual - `openspec/changes/rename-max-input-tokens/tasks.md:31` cites canonical spec paths; `tasks.md:36-37` cite `src/kani/config.py:81-100`, `src/kani/router.py:548-559`, `tests/test_input_limit_routing.py:77-272`, and `tasks.md:19-21`)
- [x] Strengthen implementation evidence for the main rename behavior with focused positive-validation coverage. (verification: unit - `tests/test_input_limit_routing.py::TestInputLimitConfig::test_max_input_tokens_must_be_positive` verifies positive integer validation; `agent-exec run -- uv run pytest tests/test_input_limit_routing.py -q` job `8cf60500462d1fb6c3dbb6b44fd14705` exited 0)

## Acceptance #4 Validation Evidence

Archive-gate validation command: `cflx openspec validate rename-max-input-tokens --archive-gate`.

## Acceptance #5 Failure Follow-up
- [x] Positive checks completed after the documentation/evidence fix. (verification: integration - `agent-exec run -- uv run pytest tests/test_input_limit_routing.py -q` job `0b2b2fde8039eb43ab3b3294961a4fe3` exited 0; `agent-exec run -- cflx openspec validate rename-max-input-tokens --strict` job `b7f504cf2311260c6bcdb38f7cdd1dd4` exited 0; `agent-exec run -- cflx openspec validate rename-max-input-tokens --archive-gate` job `e1a1fa43e76ddd020e42be671724d510` exited 0)
- [x] README routing documentation provides positive `max_input_tokens` routing metadata evidence. (verification: unit/manual - `README.md:220-229` includes `max_input_tokens` on primary and fallback object entries, `README.md:242-245` documents `{model, provider, max_input_tokens}` and skip behavior for known input limits, and `agent-exec run -- uv run pytest tests/test_input_limit_routing.py -q` job `0b2b2fde8039eb43ab3b3294961a4fe3` exited 0)
