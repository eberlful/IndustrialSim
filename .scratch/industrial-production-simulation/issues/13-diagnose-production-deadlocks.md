# 13: Diagnose production Deadlocks

**What to build:** Detect when unfinished production cannot make meaningful progress because Buffers, resources, or logistics form unresolved wait relationships, then terminate the Episode with an actionable structured diagnosis.

**Blocked by:** 02: Move Production Units through typed material flow; 04: Allocate Machines and Workers atomically; 07: Dispatch Transport Orders with shared vehicles.

Status: resolved

- [x] Domain progress is distinguished from unrelated future calendar or telemetry events.
- [x] A configurable maximum interval without domain progress can trigger Deadlock analysis.
- [x] Wait-for relationships cover Production Units, Buffers, Machines, Workers, vehicles, and route capacity.
- [x] Known wait cycles are identified deterministically without classifying ordinary finite waiting as Deadlock.
- [x] A Deadlock ends the Episode with a structured status and lists involved entities, capacities, ownership, and wait edges.
- [x] The diagnosis is available through the Application result and machine-readable CLI output.
- [x] Tests cover Buffer cycles, resource cycles, logistics cycles, false-positive avoidance, and stalled production despite irrelevant scheduled events.

## Resolution Summary

1. **Configuration**:
   - Added `DeadlockConfig` with `enabled` and duration-parsed `max_interval_without_progress` / `max_interval_without_progress_ns`.
   - Integrated `deadlock: DeadlockConfig | None` into `SimulationConfig` adhering strictly to ADR-0012 declarative validation.
2. **Analysis & Diagnosis (`industrialsim.deadlock`)**:
   - Created `WaitEdge`, `WaitForGraph`, and `DeadlockDiagnosis` dataclasses.
   - Built comprehensive wait-for relationship graph across Production Units, Buffers, Stations, Machines, Workers, Vehicles, and Route capacity.
   - Implemented deterministic cycle detection using lexicographically sorted DFS.
   - Preserved finite waiting awareness without kernel private inspection (ADR-0001), distinguishing active started operations and scheduled releases from true deadlocks.
3. **Runtime Integration & Application**:
   - Tracked `last_domain_progress_time_ns` updated exclusively on meaningful domain transitions (`_record_unit_transition`, `_record_operation_started`, `_record_operation_completed`), discriminating against recurring calendar or telemetry events.
   - Added `DEADLOCK_CHECK` kernel event scheduler and handler.
   - Terminated episodes deterministically with `status="deadlocked"`, `is_deadlocked=True`, and structured diagnosis in `EpisodeSummary` and canonical `result_hash`.
   - Emitted structured `"deadlock"` event to `audit.jsonl` and persisted `"status": "deadlocked"` to `manifest.json`.
4. **Verification**:
   - 14 comprehensive unit and end-to-end integration tests covering buffer cycles, resource cycles, logistics cycles, false-positive avoidance with long operations, and stalled production with high-frequency telemetry.
   - Full test suite (206 tests) and mypy typechecking passing with 100% success.
