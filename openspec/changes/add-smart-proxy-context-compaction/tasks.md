## Implementation Tasks

- [ ] Add smart-proxy context compaction configuration models and defaults, including independent toggles for request-time compaction and background precompaction. (verification: update `src/kani/config.py` and confirm resolved config via `uv run kani config`.)
- [ ] Implement session identifier resolution and durable compaction state storage for session snapshots, usage counters, summary cache, and job metadata. (verification: add storage code under `src/kani/` and cover persistence paths with `tests/` plus `uv run pytest tests/ -q -k compaction`.)
- [ ] Implement request-time context compaction for oversized `messages`, including protected head/tail windows and safe replacement of the middle region with a summary payload. (verification: add compaction logic in `src/kani/proxy.py` or a dedicated helper module and regression tests in `tests/` covering preserved message ordering.)
- [ ] Implement background precompaction scheduling and summary reuse on subsequent requests for the same session when a ready summary exists. (verification: add async/background flow in `src/kani/proxy.py` and `tests/` cases that cover queueing, ready-state reuse, and fallback behavior.)
- [ ] Emit operator-visible telemetry for compaction decisions, including headers, logs, and dashboard ingestion fields for queued jobs, cache hits, skips, failures, and estimated token savings. (verification: update `src/kani/proxy.py`, `src/kani/dashboard.py`, and add `tests/` coverage for new fields or `uv run pytest tests/ -q`.)
- [ ] Document the smart-proxy context strategy, configuration switches, and operational caveats for local and Docker Compose deployment. (verification: update `README.md` and related docs, then validate example commands against `src/kani/cli.py` and `uv run kani --help`.)

## Future Work

- Add Phase C features such as phantom tools, reference expansion, and tool definition reduction.
- Extend the compaction layer to additional OpenAI-compatible surfaces if kani later supports them.
- Explore per-provider compaction adapters once the core A+B path is stable.
