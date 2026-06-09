## Implementation Tasks

- [x] Replace the hardcoded offline annotation prompt slice with the runtime classification input default maximum, currently 3500 characters. (verification: unit - `tests/test_agentic_training_data.py::test_llm_feature_annotator_bounds_prompt_at_runtime_classification_default` inspects the `LLMFeatureAnnotator.annotate` request payload for an input longer than the runtime default; source evidence: `src/kani/training_data.py` uses `ANNOTATION_PROMPT_MAX_CHARS` for the slice. Completion condition: payload contains no more prompt characters than the runtime classification input default maximum.)

- [x] Make the limit traceable to runtime classification semantics via a shared/imported runtime default constant, for example extracting the `build_classification_input` default into a module-level constant used by both runtime classification and offline annotation. (verification: unit/manual - `src/kani/classification_context.py` defines `DEFAULT_CLASSIFICATION_INPUT_MAX_CHARS`, `src/kani/training_data.py` derives `ANNOTATION_PROMPT_MAX_CHARS` from it, and `tests/test_agentic_training_data.py::test_annotation_prompt_limit_matches_runtime_classification_default` asserts the alias matches the runtime default. Completion condition: there is no unexplained `prompt[:2000]`, local-only `3500`, or equivalent magic number for annotation truncation.)

- [x] Add a regression test for the prior 2000-character mismatch. (verification: unit - `tests/test_agentic_training_data.py::test_llm_feature_annotator_does_not_truncate_prompt_at_2000` passes a prompt longer than 2000 and asserts content beyond the 2000th character remains in the annotator request when still under the runtime classification input default maximum. Completion condition: reverting the limit to 2000 makes the regression test fail.)

- [x] Run targeted and relevant project checks after implementation. (verification: manual - `agent-exec run -- uv run pytest tests/test_agentic_training_data.py -q` exited 0 as job `375ef32ddb392267282966362e475bb8`; `agent-exec run -- zsh -lc 'uv run ruff check src/ tests/test_agentic_training_data.py && uv run ruff format --check src/ tests/ && uv run pyright src/'` exited 0 as job `efcf5797976600de202cfa1670b54cad`. Completion condition: command output shows no failures.)

## Future Work

Configurable annotation limits can be proposed separately if operators need workload-specific tuning.

## Final Validation

Expected archive gate: `cflx openspec validate align-annotation-input-limit --archive-gate`.

## Notes: Acceptance #1 Failure Follow-up Resolution

The prior archive commitability blocker was addressed by updating completed task verification notes with repository-verifiable source paths, test names, and runnable command evidence. The implementation also now exposes `ANNOTATION_PROMPT_MAX_CHARS` in `src/kani/training_data.py` as a named alias derived from `DEFAULT_CLASSIFICATION_INPUT_MAX_CHARS`, and `tests/test_agentic_training_data.py::test_annotation_prompt_limit_matches_runtime_classification_default` verifies the alignment directly.
