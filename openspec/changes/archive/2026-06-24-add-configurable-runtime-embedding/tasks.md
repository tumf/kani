## Implementation Tasks

- [x] Extend `EmbeddingConfig` in `src/kani/config.py` with `mode`, `timeout_seconds`, and `local_model`, preserving existing `enabled`, `model`, `provider`, `base_url`, and `api_key` compatibility (verification: unit - `uv run pytest tests/test_config.py -q -k embedding` covers default values, valid modes, invalid modes, invalid timeout, and legacy `enabled: false`).
- [x] Update embedding provider resolution so `mode=api` uses configured provider/base URL/model and `timeout_seconds`, while missing API credentials still falls back only through documented environment resolution (verification: unit - `uv run pytest tests/test_config.py tests/test_scorer.py -q -k "embedding_resolves_configured_provider or embedding_api_mode_uses_configured_timeout"`; source paths: `src/kani/config.py`, `src/kani/scorer.py`).
- [x] Add a local embedding backend abstraction used by `src/kani/scorer.py` when `embedding.mode=local`, with dependencies imported lazily and failures converted to default fallback rather than process crashes (verification: unit - `uv run pytest tests/test_scorer.py -q -k "local_embedding or embedding_failure"`; source path: `src/kani/scorer.py`).
- [x] Implement `embedding.mode=disabled` as an explicit default-only classifier mode with concise diagnostics, preserving conservative fallback values and `signals.method.raw == "default"` (verification: unit - `uv run pytest tests/test_scorer.py -q -k "embedding_disabled or default_fallback"`).
- [x] Make runtime embedding timeout use `embedding.timeout_seconds` and log expected timeout fallback as a concise warning instead of a full exception stack trace (verification: unit - `uv run pytest tests/test_scorer.py -q -k embedding_timeout`; source path: `src/kani/scorer.py`).
- [x] Add compatibility checks that surface mismatch between classifier bundle embedding metadata and runtime embedding backend/model/dimension before silent learned-classifier use (verification: unit - `uv run pytest tests/test_scorer.py -q -k "embedding_model_mismatch or embedding_dimension_mismatch"`; source path: `src/kani/scorer.py`).
- [x] Update training-side embedding configuration in `src/kani/feature_training.py` or shared resolver code so trained bundles record the same effective embedding model identity expected by runtime (verification: unit - `uv run pytest tests/test_feature_training.py -q -k embedding`; source path: `src/kani/feature_training.py`).
- [x] Update `kani doctor` classifier/embedding diagnostics to report backend mode, model/local model, timeout, classifier asset status, and default-only conditions without printing API keys (verification: integration - `uv run pytest tests/test_cli.py -q -k "doctor and embedding"`).
- [x] Update `README.md` and `config.yaml` examples to document `embedding.mode`, `timeout_seconds`, API provider/model selection, local mode constraints, and disabled mode behavior (verification: manual - inspect `README.md`, `config.yaml`, and `config.example.yaml` against `src/kani/config.py::EmbeddingConfig`; no secrets are introduced).
- [x] Run quality gates for touched areas (verification: integration - `uv run ruff check src/`, `uv run ruff format --check src/ tests/`, `uv run pyright src/`, `uv run pytest tests/test_scorer.py tests/test_config.py tests/test_cli.py -q`).

## Future Work

- Benchmark real local embedding models on mini/Docker before choosing a recommended default local model.
- Decide whether to add optional embedding result caching after backend configurability lands.

## Final Validation

Expected archive gate: `cflx openspec validate add-configurable-runtime-embedding --archive-gate`

## Acceptance #1 Failure Follow-up
- [x] Dirty working tree: config.example.yaml has unstaged changes (3 added comment lines for base_url/api_key override documentation) (verification: manual - `git diff -- config.example.yaml` and source path `config.example.yaml` show only embedding documentation comments).
- [x] Duplicate embedding: YAML key in _STARTER_CONFIG at src/kani/cli.py:393-398 and 429-434 — kani init generates a config with a silently-overridden duplicate embedding section (verification: unit - `uv run pytest tests/test_cli.py -q -k init`; source path: `src/kani/cli.py`).
- [x] Duplicate field definition in src/kani/scorer.py:99-100 — embedding_model_mismatch: bool = False declared twice consecutively (copy-paste error) (verification: unit - `uv run ruff check src/kani/scorer.py`; source path: `src/kani/scorer.py`).
