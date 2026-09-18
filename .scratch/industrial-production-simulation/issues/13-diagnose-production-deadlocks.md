# 13: Diagnose production Deadlocks

**What to build:** Detect when unfinished production cannot make meaningful progress because Buffers, resources, or logistics form unresolved wait relationships, then terminate the Episode with an actionable structured diagnosis.

**Blocked by:** 02: Move Production Units through typed material flow; 04: Allocate Machines and Workers atomically; 07: Dispatch Transport Orders with shared vehicles.

Status: ready-for-agent

- [ ] Domain progress is distinguished from unrelated future calendar or telemetry events.
- [ ] A configurable maximum interval without domain progress can trigger Deadlock analysis.
- [ ] Wait-for relationships cover Production Units, Buffers, Machines, Workers, vehicles, and route capacity.
- [ ] Known wait cycles are identified deterministically without classifying ordinary finite waiting as Deadlock.
- [ ] A Deadlock ends the Episode with a structured status and lists involved entities, capacities, ownership, and wait edges.
- [ ] The diagnosis is available through the Application result and machine-readable CLI output.
- [ ] Tests cover Buffer cycles, resource cycles, logistics cycles, false-positive avoidance, and stalled production despite irrelevant scheduled events.

