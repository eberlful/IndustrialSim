# 04: Allocate Machines and Workers atomically

**What to build:** Enable configured Operations to wait for, atomically acquire, use, and release Machines and qualified Workers while respecting shifts, pauses, and explicit interruption semantics.

**Blocked by:** 01: Run one Production Unit deterministically.

Status: resolved

- [x] Machines, individual or pooled Workers, qualifications, capacities, shifts, and breaks are strictly configurable.
- [x] An Operation starts only after all required resources can be acquired atomically; no partial reservation remains while waiting.
- [x] Resource acquisition and release are deterministic for simultaneous contenders.
- [x] Shift transitions follow an explicit handover rule and never silently interrupt work.
- [x] Configurable interruption behavior demonstrably supports Resume, Restart, and Scrap.
- [x] Application-level scenarios expose waiting time, utilization, completion, and interruption outcomes without inspecting implementation details.
- [x] Generated resource-contention tests preserve capacity and ownership invariants and cannot create a partial-reservation Deadlock.

## Answer

Issue 04 has been fully implemented across domain, configuration, simulation engine, and checkpointing:

1. **Configurable Resources & Qualifications**:
   - Added `BreakConfig`, `ShiftConfig`, `MachineConfig`, `WorkerConfig`, and `WorkerRequirementConfig` models in `src/industrialsim/config.py`.
   - Operations support `required_machines`, `required_workers` (with qualification and count), and `interruption_policy` (`resume`, `restart`, `scrap`).
   - Cross-referencing validation ensures machines, workers, and qualifications referenced in operations exist in the simulation config.

2. **Atomic Resource Allocation & Contention Determinism**:
   - Operations only start when all required machines and qualified workers can be acquired simultaneously.
   - If any required resource is unavailable, zero resources are reserved (`can_acquire_resources` returns false and no allocations are made).
   - Resource contenders waiting in `resource_waiters` are sorted and served deterministically using stable tie-breaking: `(waiting_since_ns, priority, station_id, unit_id)`.

3. **Shift Transitions & Interruption Semantics**:
   - Explicit handover rules (`handover`, `run_off`, `interrupt`):
     - `handover`: If an incoming qualified worker with available capacity is on shift, ownership transfers seamlessly without operation interruption. If no incoming worker is available, the operation is interrupted according to its policy.
     - `run_off`: Active workers complete their current operation before clocking off, but accept no new assignments.
     - `interrupt`: Operations are interrupted upon shift end.
   - Interruption policies:
     - `resume`: Preserves completed elapsed time, pauses, and resumes remaining duration when resources return.
     - `restart`: Discards partial progress and restarts from 0 duration when resources return.
     - `scrap`: Aborts the operation, marks the unit as `scrapped`, moves it to `terminal` state, and frees the station and resources.

4. **Metrics Exposure**:
   - `MachineSummary` and `WorkerSummary` expose `total_busy_time_ns`, `total_idle_time_ns`, `total_break_time_ns`, `total_off_shift_time_ns`, `operations_completed`, and `utilization`.
   - `StationSummary` exposes `total_waiting_time_ns`, `total_busy_time_ns`, `total_blocked_time_ns`, `interrupted_count`, `resumed_count`, `restarted_count`, and `scrapped_count`.

5. **Invariants & Equivalence**:
   - Property tests with Hypothesis (`tests/test_resource_contention.py`) verify capacity bounds, deadlock-free completion, and determinism.
   - Checkpoint equivalence (`tests/test_checkpoint_equivalence.py`) verifies that pausing mid-operation, saving, and resuming produces exact bit-for-bit equivalence with uninterrupted runs.

