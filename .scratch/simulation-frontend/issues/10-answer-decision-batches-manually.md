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

Final validation: 333 Python tests passed, 1 skipped; all 17 browser workflows passed. Python typechecks for five changed modules and TypeScript typecheck/frontend build passed. The manual browser workflow also covers multiple requests for one target, keeping all requests visible while submitting one shared action.

Code review against starting commit `06360b31f0ac29596bee2d14c37a6cc540de6909`: Standards: 0 remaining findings; Spec: 0 remaining findings. Review fixes preserve Worker assignments/qualifications in checkpoints, apply direct batch effects before resource allocation, group same-target forms with unique request IDs, restrict routes to the Production Unit's process plan, and reuse existing dispatch policy rules for Vehicle suitability and shared Route capacity. Public regressions verify rejected proposals leave state and pending batches intact, correction succeeds, and proposal ordering does not skip effects.

The 18 manual public session/worker tests also passed against exported committed sources, with only the existing workspace's Python 3.12 runtime/YAML compatibility adaptations applied to that temporary verification copy. Existing unrelated workspace changes remain outside the implementation commits.
