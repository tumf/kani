## Specification Tasks

- [x] Update README smart-proxy compaction example to use `summary_profile` instead of `summary_model` (expected canonical result: documentation matches the current `SyncCompactionConfig.summary_profile` field)
- [x] Update README prose to describe empty `summary_profile` fallback through default routing profile resolution (expected canonical result: operators understand that summary model selection is profile-based, not raw model-ID based)
- [x] Verify no active documentation still instructs operators to configure `summary_model` (expected canonical result: `summary_model` appears only in archived changes or intentional implementation-internal parameter names, not in current config docs)

## Future Work

- Consider adding an explicit config validation message for users who still provide legacy `summary_model`.

## Final Validation

Archive validation is the authoritative final OpenSpec validation gate.
Expected archive gate: `cflx openspec validate fix-compaction-summary-docs --archive-gate`
