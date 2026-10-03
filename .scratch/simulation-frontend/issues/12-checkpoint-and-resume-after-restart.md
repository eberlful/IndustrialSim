# 12: Create Checkpoints and resume after restart

**What to build:** Create a durable Checkpoint explicitly and restore a compatible saved Episode after restarting the local backend, including an unanswered manual Decision Batch.

**Blocked by:** 10: Answer Decision Batches manually.

**Status:** ready-for-agent

- [x] An explicit UI action creates a durable Checkpoint at a consistent state and identifies its originating Episode/configuration.
- [x] After backend restart, the user can select a saved Checkpoint and explicitly restore it; browser reconnect alone does not restore or restart execution.
- [x] Existing schema/kernel/configuration/model/plugin compatibility validation rejects incompatible Checkpoints with actionable errors and no invalid continuation.
- [x] Restored pending manual Decision Batches wait for input again and retain the correct request/state identity; stale prior submissions cannot apply twice.
- [x] Continuation writes into a new unique result directory with parent/checkpoint provenance, preserving all earlier complete and incomplete artifacts.
- [x] The UI displays the restored Episode using its own configuration, independently of newer project drafts.
- [x] Recovery is limited to the saved Checkpoint and supported Baseline/manual modes; automatic periodic snapshots or unsupported provider history are not implied.
- [x] Public-session tests compare restored and uninterrupted execution and verify provenance, compatibility rejection and pending manual input.
- [x] A browser end-to-end workflow creates a Checkpoint, restarts the service, restores and completes the Episode without overwriting earlier artifacts.


## Comments

Implemented explicit durable Checkpoint creation at paused or pending Decision Batch boundaries, a project-local saved Checkpoint selector, and explicit restore after backend restart. Reconnect does not restore an Episode. Recovery supports Baseline/manual modes and validates the existing portable schema/kernel/configuration/model/plugin metadata before reserving continuation artifacts. Restored Episodes remain paused or awaiting their preserved Decision Batch, use a new service identity to reject stale submissions, and write into an exclusively created result directory with parent-run and Checkpoint-hash provenance. Their graph and read-only configuration come from the frozen Episode rather than a newer project draft.

Continuation now retains Station configuration/reconfiguration and inspection overrides, accumulated strategic costs, Buffer observation history and the last domain-progress time. Restore uses the saved event queue exactly, preventing an already-fired safe-point trigger from being re-scheduled. Artifact run identity is separate from simulator Episode identity, preserving telemetry and Decision Request equivalence while identifying unique service-owned continuations.

Validation: 346 Python tests passed, 1 skipped; all 20 browser workflows passed. Python typechecking passed for all 40 source files; TypeScript typechecking and frontend build passed. Public-session tests compare restored and uninterrupted execution, preserve pending manual and Buffer requests, reject incompatible/corrupted Checkpoints, verify manual-effect persistence and provenance, and reject old/repeated submissions. The browser workflow creates a Checkpoint, stops and restarts a real service, confirms no automatic restore, opens a newer draft, restores the original Episode and completes it while checking earlier incomplete artifacts remain byte-for-byte unchanged.

The 22 Checkpoint session/serialization/equivalence tests also passed against exported committed sources with only the pre-existing workspace’s Python 3.12 and YAML runtime adaptations applied to that temporary copy. Unrelated workspace changes remain outside the implementation commits.

Code review against starting commit `772e1a77438468fdd2f803954ead7e906f2af7cc`: Standards: 0 remaining findings; Spec: 0 remaining findings. The optional lifecycle-guard duplication was resolved with a shared active-state definition. Implementation commits: `63eae08`, `f5c9eb3`, `6d6b513`.
