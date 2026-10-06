# 15: Run and compare the reference automotive Plant

**What to build:** Deliver the complete V1 reference experiment: a configurable automotive Plant spanning body shop, paint shop, and final assembly, compared under the deterministic baseline and an in-process Decision Provider over a production week.

**Blocked by:** 05: Route Process Plans and observe quality; 06: Degrade, fail, and maintain Machines; 07: Dispatch Transport Orders with shared vehicles; 09: Expose production-control Actions to a Decision Provider; 10: Branch counterfactual decisions from a Checkpoint; 12: Export metrics, Reward, and Parquet telemetry; 13: Diagnose production Deadlocks; 14: Swap a macro Station for a trusted plugin micro model.

Status: resolved

- [x] The reference Plant contains two parallel body-shop Stations, paint pretreatment, paint booth, drying, sequential final assembly, bounded Buffers, shared vehicles, rework, and Scrap.
- [x] Its Production Plan contains at least two product variants with release times and due dates over a configurable production week.
- [x] Machines degrade and fail, Workers follow qualifications and shifts, inspections reveal imperfect Quality Findings, and maintenance competes for resources.
- [x] Synthetic parameters are clearly identified as uncalibrated in configuration and run manifests.
- [x] The deterministic baseline and an in-process Decision Provider run from identical Episode inputs and produce a structured metric and Reward comparison.
- [x] At least one Decision Point produces two controlled Counterfactual Branches with complete audit and telemetry artifacts.
- [x] Warm-up exclusion, hard constraints, Fallback behavior, and terminal status are reflected in summaries.
- [x] Repeated executions produce identical result hashes and the primary Application-level acceptance scenario passes end to end.

## Answer

Implemented the complete reference automotive plant configuration, policy comparison API, and comprehensive acceptance test suite:
1. **Reference Plant Model (`examples/reference_automotive_plant.yaml`)**:
   - Areas complying with `GLOSSARY.md`: `area-body-construction`, `area-paint-application`, `area-final-assembly`.
   - Stations covering parallel body construction (`st-body-1`, `st-body-2`), paint pretreatment (`st-paint-pretreat`), spray booth (`st-paint-booth`), drying (`st-paint-drying`), sequential assembly (`st-assembly-1`, `st-assembly-2`), inspection (`st-inspect`), and rework (`st-rework`).
   - Shared vehicles (`agv-1`, `agv-2`) and bounded buffers across transfer points.
   - Machine degradation, stochastic failure, condition-threshold maintenance, planned disruptions, and shifts/breaks for workers with maintenance qualifications competing for resources.
   - Quality inspection with sensitivity and false-positive rates, disposition routing to rework, rework restoration probability, rework limits, and scrap.
   - Explicit uncalibrated synthetic parameter declarations in configuration and run manifests.
2. **Policy Comparison & Counterfactual Branching (`src/industrialsim/application.py`)**:
   - `PolicyComparisonResult` and typed comparison components (`MetricDelta`, `RewardComparison`, `HardConstraintsComparison`, `FallbacksComparison`, `StatusComparison`).
   - `EpisodeSummary.compare_with(...)` computing structured delta metrics, reward breakdowns, constraint violations, fallbacks, and statuses.
   - `compare_policies(...)` executing baseline policy and custom decision provider side-by-side, exporting `comparison_summary.json` and manifests.
   - Counterfactual branching validating decisions, writing per-branch Parquet telemetry and audit trails.
3. **Acceptance Tests (`tests/test_reference_automotive_plant_e2e.py`)**:
   - 6 end-to-end acceptance tests verifying plant structure, uncalibrated parameter metadata, policy comparison, determinism (`s1.result_hash == s2.result_hash`), downstream rework/scrap/maintenance, and counterfactual branching artifacts.

