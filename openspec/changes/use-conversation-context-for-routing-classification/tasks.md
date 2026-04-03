## Implementation Tasks

- [ ] 1. Define a shared classification-input builder for routing classification context (verification: repository contains a single reusable function/module that turns message arrays into the text used for classification in both runtime and training flows)
- [ ] 2. Replace last-user-only extraction in `src/kani/router.py` with context-aware classification input construction (verification: `Router` no longer classifies from only the final user message and tests cover short follow-up messages inheriting prior intent)
- [ ] 3. Update `src/kani/scorer.py` integration so classification operates on the context-aware input without changing public result shape (verification: scorer still returns stable `ClassificationResult` fields while consuming the new input text)
- [ ] 4. Update training-data generation to use the same classification input semantics as runtime (verification: `src/kani/training_data.py` or related training utilities build datasets from the same context-aware representation rather than isolated final prompts)
- [ ] 5. Extend routing/logging tests to preserve replayability and context visibility (verification: tests confirm logs retain enough classification-context evidence to reproduce or inspect scoring decisions)
- [ ] 6. Add regression tests for contextual follow-up prompts such as "はい", "続けて", or equivalent short continuations (verification: `uv run pytest tests/ -q` includes cases where last-message-only classification would misclassify but context-aware classification succeeds)
- [ ] 7. Run repository quality gates after the classification-input change (verification: `uv run ruff check src/`, `uv run ruff format --check src/ tests/`, `uv run pyright src/`, `uv run pytest tests/ -q`, and `uv build` all pass)

## Future Work

- Revisit how much assistant-authored context should be included if future evaluations show overfitting to assistant phrasing.
- Consider aligning routing classification context with compaction/session-summary artifacts if replay datasets grow large.
