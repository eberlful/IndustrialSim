# 05: Route Process Plans and observe quality

**What to build:** Materialize a Production Plan with two product variants, route each Production Unit through its Process Plan, and model hidden quality changes that become actionable only through imperfect Quality Findings, including a complete rework and Scrap path.

**Blocked by:** 02: Move Production Units through typed material flow; 04: Allocate Machines and Workers atomically.

Status: resolved

- [x] A Production Plan declares release times, variants, quantities, and optional due dates and is fully materialized before the Episode starts.
- [x] Production Unit identities are deterministic and stable across repeated Episodes and Counterfactual preparation.
- [x] Each variant has a declarative Process Plan with required Operations and compatible Station alternatives.
- [x] A deterministic Routing Policy selects a compatible Station and route without rewriting Process Plan history.
- [x] Operations can alter latent Quality State without exposing hidden truth to normal observations.
- [x] Inspection produces Quality Findings with configurable sensitivity and false-positive behavior under deterministic randomness.
- [x] A Quality Finding can send a Production Unit through an explicit rework cycle or to Scrap while preserving history and location invariants.
- [x] End-to-end tests demonstrate both variants, undetected defects, detected defects, rework, and Scrap.

## Answer

Issue 05 has been fully implemented across configuration, domain models, random streams, routing policy, and simulation execution:

1. **Production Plan Materialization (ADR 0015)**:
   - Declarative `ProductionPlanEntryConfig` specifying `variant`, `quantity`, `release_time`, and optional `due_date`.
   - Deterministic pre-episode materialization generates canonical, reproducible `ProductionUnitConfig` identities (e.g. `{prefix}-{index}`) prior to episode start.

2. **Declarative Process Plans & Routing Policy (ADR 0014)**:
   - `ProcessPlanStepConfig` and `ProcessPlanConfig` declare required operations and compatible station alternatives per product variant.
   - Deterministic multi-criteria routing policy ranks routes across downstream availability, direct target alignment, target station availability, queue load, shortest transit path distance, and stable route ID tie-breaking without mutating history.

3. **Latent Quality State vs Observed Findings (ADR 0008)**:
   - `ProductionUnit` maintains latent ground truth `quality_state` and `defects` separate from observed `findings: list[QualityFinding]`.
   - Defect generation and rework restorations update the latent physical condition, while `InspectionConfig` (with configurable `sensitivity` and `false_positive_rate`) samples findings.
   - Scrapped units preserve physical quality state without conflating it with observation dispositions.

4. **Counterfactual PRNG Streams (ADR 0002)**:
   - Implemented standard counter-based Philox 4x32 PRNG (`Philox4x32`) and checkpointable `SemanticRandomStream`.
   - Draws are addressed by `(stream_kind, unit_id:operation_id, mode)` and tracked across occurrences, preserving reproducibility and common randomness across counterfactual branches regardless of station arrival interleaving.

5. **Explicit Rework Cycles & Scrap Paths**:
   - Quality inspection findings can direct defective units to explicit rework stations and operations (`disposition_on_defect: rework`, `max_reworks`), restoring quality and re-routing back for re-inspection while preserving `process_step_index` and full location transition history.
   - Detected scrap immediately transitions units to `TERMINAL` state at location `"terminal"`, increments station `scrapped_count`, and releases upstream bottlenecks.

6. **Comprehensive End-to-End Verification & Checkpoint Equivalence (ADR 0009)**:
   - End-to-end suites demonstrate multiple variants, detected defects, undetected defects, rework loops, scrap, and bit-level checkpoint/restore equivalence mid-rework.
