---
change_type: implementation
priority: medium
dependencies: []
references:
  - openspec/specs/config/spec.md
  - src/kani/cli.py
  - src/kani/scorer.py
  - src/kani/feature_training.py
  - models/tier_classifier.pkl
  - models/feature_classifier.pkl
---

# Add `kani doctor` diagnostics for configuration and classifier assets

**Change Type**: implementation

## Problem

Open issue #1 identified that the shipped classifier pickle assets can drift from current runtime behavior. The current runtime scorer no longer loads the legacy `tier_classifier.pkl`, but the repository still contains classifier artifacts and training code that can confuse operators.

There is no `kani doctor` or `kani check` command to make this state explicit. Users may see unclear routing behavior or assume a bundled classifier is active when it is not.

## Proposed Solution

Add a read-only `kani doctor` CLI command that validates operational health without printing secrets.

Initial diagnostics should cover:

- Config loading succeeds in strict mode when a config is expected.
- Providers and profiles are present.
- Model metadata surfaces are unambiguous (`model_rules` vs legacy `model_capabilities`).
- Classifier assets in `models/` are detected and reported with clear status. In the current runtime, bundled pickle assets are reported as present but not loaded by routing unless code changes later reintroduce runtime asset loading.
- The command exits non-zero only for actionable errors; warnings should be reported but not fail by default.

## Acceptance Criteria

- `uv run kani doctor --config <path>` prints a concise human-readable report.
- The report never prints raw API keys.
- Existing `models/tier_classifier.pkl` is reported as legacy/unused instead of silently implying it is active.
- Existing `models/feature_classifier.pkl` is reported as present but not loaded by current runtime routing, unless implementation evidence in `src/kani/scorer.py` shows otherwise.
- Invalid config returns non-zero and prints a clear error.
- Tests cover successful config diagnostics, invalid config failure, and classifier asset reporting.

## Explicit Completion Conditions

- Add a `doctor` Click command to `src/kani/cli.py`.
- Add diagnostics helpers in `src/kani/cli.py` or a small new module under `src/kani/` if needed. The classifier asset diagnostic should base "active" only on explicit runtime loading evidence, not on file presence alone.
- Add tests under `tests/test_cli.py` that call the CLI via Click's testing utilities and assert masked output, invalid-config behavior, and expected classifier asset warning lines.
- Run `uv run ruff check src/`, `uv run pyright src/`, and `uv run pytest tests/ -q`.

## Out of Scope

- Re-enabling runtime loading of pickle classifier assets.
- Replacing or regenerating classifier pickle files.
- Adding network probes to upstream providers.
- Adding a full interactive troubleshooting wizard.
- Claiming bundled classifier pickle files are active solely because they exist on disk.
