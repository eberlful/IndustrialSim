# 09: Observe, pause and continue an Episode

**What to build:** Observe live production and inspect individual entities, then pause and continue the same Episode at consistent states.

**Blocked by:** 08: Run a Baseline Episode independently of the browser.

**Status:** ready-for-agent

- [x] The graph displays current Station/Buffer occupancy and relevant resource status from authoritative snapshots.
- [x] Selecting entities opens resource and Production Unit details; supported raw metrics and ordered paginated events are available beside the graph.
- [x] Simulated time and wall-clock time are labeled separately; display updates are throttled independently of engine advancement.
- [x] Pause takes effect at a consistent simulation boundary; continue resumes the same Episode without losing events or changing its inputs.
- [x] Snapshots, pagination, browser refresh and intermediate pauses neither finalize the Episode nor duplicate terminal telemetry, reward or summary records.
- [x] Event pagination preserves ordering and avoids requiring the full audit history in browser memory.
- [x] Public-session checks compare paused/resumed outcomes with uninterrupted execution and verify ordered lossless artifacts under frequent reads.
- [x] A browser workflow observes occupancy, inspects an entity, pauses and continues; responsiveness checks use state transitions rather than brittle timing assumptions.

## Comments

Added public `EpisodeSession.observe()` for isolated Station/Buffer occupancy,
Machine/Worker status and allocations, Production Unit details and raw metrics.
Ordered audit events use validated bounded cursor pages without copying the full
history. Intermediate observations preserve deterministic outcomes and artifacts.

The service-owned worker acknowledges pause only at a settled simulation boundary,
then continues the same Episode with frozen inputs. Active and paused Episodes
reject replacement starts; controls and event cursors are scoped to Episode IDs.
Published snapshots are throttled independently of engine advancement. Shutdown
wakes paused workers and leaves unfinished output incomplete.

The browser labels simulated time and elapsed wall-clock time separately, overlays
occupancy and resource availability on the frozen Episode graph, opens live entity
and Production Unit details, displays current metrics and keeps only one 50-record
event page in memory. Draft and Episode graphs can be selected separately. Refresh
reattaches to paused execution without advancing or finalizing it. Browser outcome
snapshots omit full Production Unit histories; exact event timestamps use strings.

Validation: 315 Python tests passed, 1 skipped; all 16 browser workflows passed.
Python typechecks for changed modules and the TypeScript build/typecheck pass.
Public-session checks cover occupancy, allocations, snapshot isolation, invalid
cursors, frozen graph inputs and exact resumed/uninterrupted summaries, audit
records and telemetry. Browser checks observe, inspect resources and a Production
Unit, paginate, reject stale controls, refresh a pause and continue to completion.

Code review against starting commit `1ec39ca`: Standards: 0 remaining findings;
Spec: 0 remaining findings. Review fixes share pagination validation and resource
association, include dynamically allocated Machines, and keep the frozen Episode
graph available when the next Episode's draft is malformed. The browser workflow
covers that case and restores its shared project draft afterward. Final full
Python and browser suites retain the validation counts above. Existing unrelated
workspace edits remain outside this commit.
