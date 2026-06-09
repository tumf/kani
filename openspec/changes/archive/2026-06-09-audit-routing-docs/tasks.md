## Specification Tasks

- [x] Promote config metadata documentation requirements to canonical `config` spec. Expected canonical result: `config` states `model_rules` is the primary model metadata list, `model_capabilities` is normalized as a legacy alias only when `model_rules` is unset, and capability-required routing fails closed when no configured candidate declares required capabilities. Verification: manual - compared `openspec/specs/config/spec.md` against `src/kani/config.py` (`KaniConfig._normalize_legacy_model_capabilities`, `model_rules`) and `src/kani/router.py` capability filtering semantics.

- [x] Promote routing provider precedence and literal model ID documentation requirements to canonical `routing` spec. Expected canonical result: `routing` documents model-entry provider, tier provider, and default provider precedence, and clarifies model IDs are sent literally to the selected provider. Verification: manual - compared canonical spec with `TierModelConfig` and `SmartRouter._resolve_provider_name` call sites; provider parsing is separate from literal model ID forwarding.

- [x] Promote smart-proxy session documentation requirements to canonical `smart-proxy-context-compaction` spec. Expected canonical result: compaction session requirements describe explicit headers and no-header cases without stale derived-session claims; no-header requests have no session ID and therefore cannot use cache reuse, persistence, incremental summarization, or background precompaction, while inline compaction may still run. Verification: manual - compared canonical spec with `resolve_session_id` and `_resolve_compaction`; no-header behavior is documented as `none`, not derived.

- [x] Update README/config examples as part of this docs/spec-only change application to match the canonical requirements. Expected canonical result: user-facing docs explain model metadata, provider overrides, literal model IDs, and compaction session behavior consistently. Verification: manual - updated README and config.example.yaml so model metadata, provider precedence, literal model IDs, and no-header compaction behavior align with canonical specs.

- [x] Track any code/spec contradiction discovered during the audit separately. Expected canonical result: this spec-only change does not silently redefine runtime behavior when code does not match. Verification: manual - compared updated docs/spec text against current code paths and found no new code/spec contradiction requiring a separate implementation issue/proposal.

## Future Work

Implementation proposals may be needed if the audit discovers code behavior that should change rather than documentation that should change.

## Final Validation

Expected archive gate: `cflx openspec validate audit-routing-docs --archive-gate`.

## Acceptance #1 Failure Follow-up
- [x] OpenSpec/要件側の主要確認は通過しています: `cflx openspec validate audit-routing-docs --strict` と `cflx openspec validate audit-routing-docs --archive-gate` は Validation passed。README/config/spec は `model_rules` primary、legacy `model_capabilities`、capability fail-closed、provider precedence、literal model ID、no-header compaction behavior を記述しています。再検証で `tasks.md` に unchecked `- [ ]` が残らない状態に更新しました。
- [x] コミットパスの pre-commit hook blocker を解消しました。`tests/test_proxy_reload.py` の `ruff format` 変更を保持し、`agent-exec run -- prek run --all-files` を再実行して ruff / ruff format が Passed、job `a1cf754916d64453f02edeaba3dc9be5` が exit_code 0 で完了したことを確認しました。
