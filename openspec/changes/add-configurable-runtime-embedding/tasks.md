## Implementation Tasks

- [ ] Extend `EmbeddingConfig` in `src/kani/config.py` with `mode`, `timeout_seconds`, and `local_model`, preserving existing `enabled`, `model`, `provider`, `base_url`, and `api_key` compatibility (verification: unit - `uv run pytest tests/test_config.py -q -k embedding` covers default values, valid modes, invalid modes, invalid timeout, and legacy `enabled: false`).
- [ ] Update embedding provider resolution so `mode=api` uses configured provider/base URL/model and `timeout_seconds`, while missing API credentials still falls back only through documented environment resolution (verification: unit - config/scorer resolver tests assert selected base URL, model, and timeout without exposing secrets).
- [ ] Add a local embedding backend abstraction used by `src/kani/scorer.py` when `embedding.mode=local`, with dependencies imported lazily and failures converted to default fallback rather than process crashes (verification: unit - mocked local backend returns a deterministic vector and tests prove `client.embeddings.create` is not called).
- [ ] Implement `embedding.mode=disabled` as an explicit default-only classifier mode with concise diagnostics, preserving conservative fallback values and `signals.method.raw == "default"` (verification: unit - `uv run pytest tests/test_scorer.py -q -k "embedding_disabled or default_fallback"`).
- [ ] Make runtime embedding timeout use `embedding.timeout_seconds` and log expected timeout fallback as a concise warning instead of a full exception stack trace (verification: unit - caplog test confirms timeout returns default fallback and warning text does not include traceback).
- [ ] Add compatibility checks that surface mismatch between classifier bundle embedding metadata and runtime embedding backend/model/dimension before silent learned-classifier use (verification: unit - bundle mismatch tests cover model identity and dimension mismatch paths).
- [ ] Update training-side embedding configuration in `src/kani/feature_training.py` or shared resolver code so trained bundles record the same effective embedding model identity expected by runtime (verification: integration - training helper test or mocked training path asserts bundle metadata matches resolved config).
- [ ] Update `kani doctor` classifier/embedding diagnostics to report backend mode, model/local model, timeout, classifier asset status, and default-only conditions without printing API keys (verification: integration - `uv run pytest tests/test_cli.py -q -k "doctor and embedding"`).
- [ ] Update `README.md` and `config.yaml` examples to document `embedding.mode`, `timeout_seconds`, API provider/model selection, local mode constraints, and disabled mode behavior (verification: manual - docs examples match `EmbeddingConfig` fields and no secrets are introduced).
- [ ] Run quality gates for touched areas (verification: integration - `uv run ruff check src/`, `uv run ruff format --check src/ tests/`, `uv run pyright src/`, `uv run pytest tests/test_scorer.py tests/test_config.py tests/test_cli.py -q`).

## Future Work

- Benchmark real local embedding models on mini/Docker before choosing a recommended default local model.
- Decide whether to add optional embedding result caching after backend configurability lands.

## Final Validation

Expected archive gate: `cflx openspec validate add-configurable-runtime-embedding --archive-gate`
