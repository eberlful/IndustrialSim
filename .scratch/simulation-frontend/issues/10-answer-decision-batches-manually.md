# 10: Answer Decision Batches manually

**What to build:** Choose Baseline or manual decisions, advance to the next Decision Batch, inspect every request and submit a complete set of valid actions.

**Blocked by:** 09: Observe, pause and continue an Episode.

**Status:** ready-for-agent

- [x] Setup offers automatic Baseline and manual modes; next-Decision-Batch control reaches a consistent shared observation boundary.
- [x] Manual mode displays all pending Decision Requests with applicable schema-based action forms and keeps simulated time frozen while awaiting input.
- [x] Submission validates individual actions and joint compatibility against the intended batch; only a complete valid batch is applied atomically.
- [x] Invalid or conflicting input produces actionable errors and remains editable without time advancement or implicit fallback.
- [x] Actual provider failure/abort remains distinct from form rejection and honors existing configured fallback/abort semantics.
- [x] Episode/batch identity prevents stale responses and repeated submissions from answering another batch or applying effects twice.
- [x] Valid actions and decision provenance use existing lossless audit behavior; existing action schemas are reused rather than duplicated in service rules.
- [x] Public-session tests cover all applicable action-form contracts, shared state, conflicts, correction, atomic application and stale/repeated submission.
- [x] A browser workflow reaches a manual batch, corrects a rejected proposal and applies the complete valid batch once.

## Comments

Implemented Baseline/manual selection, stable batch boundaries, schema-derived forms, editable validation failures and atomic submissions with Episode/batch identity. Public session tests exercise every action contract, shared-state conflicts, correction, provenance and selected resource effects. Worker tests cover both manual control and configured provider failure semantics. Browser tests verify rejected proposals stay editable and complete valid batches apply once.

Validation: Python suite 328 passed, 1 skipped before the final selected-Vehicle regression; browser suite 17 passed; Python and TypeScript type checks and frontend build passed. Final review and verification follow.
