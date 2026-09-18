# 15: Run and compare the reference automotive Plant

**What to build:** Deliver the complete V1 reference experiment: a configurable automotive Plant spanning body shop, paint shop, and final assembly, compared under the deterministic baseline and an in-process Decision Provider over a production week.

**Blocked by:** 05: Route Process Plans and observe quality; 06: Degrade, fail, and maintain Machines; 07: Dispatch Transport Orders with shared vehicles; 09: Expose production-control Actions to a Decision Provider; 10: Branch counterfactual decisions from a Checkpoint; 12: Export metrics, Reward, and Parquet telemetry; 13: Diagnose production Deadlocks; 14: Swap a macro Station for a trusted plugin micro model.

Status: ready-for-agent

- [ ] The reference Plant contains two parallel body-shop Stations, paint pretreatment, paint booth, drying, sequential final assembly, bounded Buffers, shared vehicles, rework, and Scrap.
- [ ] Its Production Plan contains at least two product variants with release times and due dates over a configurable production week.
- [ ] Machines degrade and fail, Workers follow qualifications and shifts, inspections reveal imperfect Quality Findings, and maintenance competes for resources.
- [ ] Synthetic parameters are clearly identified as uncalibrated in configuration and run manifests.
- [ ] The deterministic baseline and an in-process Decision Provider run from identical Episode inputs and produce a structured metric and Reward comparison.
- [ ] At least one Decision Point produces two controlled Counterfactual Branches with complete audit and telemetry artifacts.
- [ ] Warm-up exclusion, hard constraints, Fallback behavior, and terminal status are reflected in summaries.
- [ ] Repeated executions produce identical result hashes and the primary Application-level acceptance scenario passes end to end.

