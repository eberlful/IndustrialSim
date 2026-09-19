# 06: Degrade, fail, and maintain Machines

**What to build:** Make Machine condition operationally relevant by degrading Health State during use, changing cycle and quality behavior, producing scheduled and stochastic failures, and allowing resource-consuming inspection, maintenance, and repair.

**Blocked by:** 04: Allocate Machines and Workers atomically; 05: Route Process Plans and observe quality.

Status: resolved

- [x] Machine configuration supports normalized Health State, operating modes, degradation rates, and optional named physical state variables.
- [x] Use, idle time, inspection, maintenance, and repair change Health State through explicit configurable policies.
- [x] Health State observably affects cycle time, defect probability, and failure hazard.
- [x] Planned disruptions and stochastic time-to-failure and repair duration are reproducible for a fixed seed.
- [x] Failure interruption respects the Operation's Resume, Restart, or Scrap semantics.
- [x] Maintenance and repair consume simulation time and can require a qualified maintenance Worker.
- [x] Maintenance restores Health State only to its configured level rather than silently returning every Machine to perfect condition.
- [x] End-to-end tests cover preventive maintenance, unexpected failure, repair contention, quality impact, and deterministic replay.

## Answer

Issue 06 has been fully implemented across configuration, domain models, simulation engine, checkpointing, and testing:

1. **Machine Health & Mode Configuration (ADR 0007, ADR 0012)**:
   - Configurable normalized Health State in `[0.0, 1.0]` (`initial_health`).
   - Named operating modes via `MachineModeConfig` with multipliers for cycle time, degradation, defect probability, and failure hazard (`modes`, `operating_mode`).
   - Named physical state variables (`physical_state`) mapped to float measurements (e.g. temperature, vibration).
   - Explicit configurable policies: `DegradationPolicyConfig`, `MaintenancePolicyConfig`, `MachineInspectionPolicyConfig`, `FailurePolicyConfig`, and `PlannedDisruptionConfig`.

2. **Health Degradation Across Use, Idle Time, Inspection, Maintenance, and Repair**:
   - `Machine.update_metrics(time_ns)` calculates elapsed busy and idle durations, applying busy use rates (`use_rate_per_s`) and idle rates (`idle_rate_per_s`) scaled by mode degradation multipliers, and integrates physical state rates.
   - Maintenance restores health strictly to `restored_health` (defaulting to configured target, not resetting to 1.0).
   - Planned disruptions and failure repairs restore health strictly to `repaired_health`.
   - Inspection policies can calibrate or restore health (`inspect(time_ns, restored_health, health_delta)`).

3. **Operational Impact of Health State**:
   - **Cycle time**: `_compute_effective_operation_duration` applies `(1.0 + cycle_time_factor * (1.0 - health)) * cycle_time_multiplier` to stretch or compress operation duration.
   - **Defect probability**: `_compute_effective_defect_probability` calculates latent defect generation probability incorporating `defect_probability_factor * (1.0 - health)` scaled by mode multiplier.
   - **Failure hazard**: `_schedule_next_failure` scales MTTF and hazard rates by `(1.0 + hazard_factor * (1.0 - health)) * hazard_multiplier`.

4. **Reproducible Planned Disruptions & Stochastic Failures / Repairs (ADR 0002)**:
   - Planned disruptions (`DISRUPTION_START`, `COMPLETE_REPAIR`) execute at deterministic simulated timestamps.
   - Stochastic time-to-failure (`ttf`) and stochastic repair duration (`mttr`) draw from `SemanticRandomStream` addressed per machine (`("machine_failure", mach.id, "ttf")` and `("machine_repair", mach.id, "duration")`), ensuring exact replay and counterfactual stability for fixed seeds.

5. **Interruption Semantics (Resume, Restart, Scrap)**:
   - Machine failures and disruptions immediately interrupt any active operations across affected stations via `_interrupt_operation`.
   - Operations respect their configured interruption policy: `"resume"` preserves work completed and queues token for continuation; `"restart"` invalidates progress and requeues for full duration; `"scrap"` marks unit terminal and triggers upstream pull.

6. **Worker Requirements & Repair Contention**:
   - Maintenance and repairs require qualified workers (`WorkerRequirementConfig`, e.g. `"maintenance"` qualification).
   - Contention for technicians between machines is resolved via deterministic FIFO queues (`maintenance_waiters`).

7. **Full Checkpoint / Restore Equivalence (ADR 0009)**:
   - `MachineSnapshot` and `DomainStateSnapshot` preserve machine health, mode, failure/maintenance flags, timestamps, metrics, pending maintenance waiters, and active maintenance allocations.
   - Mid-disruption and mid-maintenance checkpointing produces identical summary results and SHA-256 result hashes compared to continuous simulation.

