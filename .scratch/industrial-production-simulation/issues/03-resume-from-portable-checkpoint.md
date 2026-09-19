# 03: Resume an Episode from a portable Checkpoint

**What to build:** Allow a user to snapshot a running Episode, persist the complete continuation state, inspect its metadata, and resume it in a fresh process with the same externally visible result as an uninterrupted run.

**Blocked by:** 01: Run one Production Unit deterministically.

Status: resolved

- [x] A Checkpoint contains schema and kernel versions, model and configuration hashes, simulation time, next sequence, event queue, explicit domain state, root seed, and random occurrence counters.
- [x] Persisted events and state contain data records only and do not depend on generators, closures, callbacks, or live objects.
- [x] The Application API can create, serialize, inspect, restore, and continue a Checkpoint.
- [x] Thin `resume` and Checkpoint-oriented `inspect` CLI behavior uses the same Application API.
- [x] An uninterrupted run and a checkpointed/resumed run produce identical summaries, result hashes, and observable event order.
- [x] Incompatible schema, kernel, model, configuration, or plugin metadata is rejected with a specific diagnostic.
- [x] Checkpoint writes cannot leave a partial file that appears valid.

## Answer

Issue 03 has been fully implemented and verified:
- **Portable Checkpoint Structure**: Implemented `Checkpoint` and `CheckpointInspection` in `src/industrialsim/checkpoint.py`, containing `schema_version`, `kernel_version`, `model_hash`, `config_hash`, `simulated_time_ns`, `sequence_counter`, `events_processed`, `event_queue`, explicit `domain_state`, `root_seed`, `random_occurrence_counters`, `plugin_metadata`, and `checksum`.
- **Pure Data Records**: Persisted events and state use primitive JSON-serializable structures without generators, closures, callbacks, or live domain objects.
- **Application API**: `create_checkpoint`, `save_checkpoint`, `load_checkpoint`, `serialize_checkpoint`, `deserialize_checkpoint`, `inspect_checkpoint`, `restore_checkpoint`, and `resume_episode` are exposed in `src/industrialsim/application.py`.
- **Engine Encapsulation**: Simulation state and handler logic are encapsulated in `EpisodeEngine`, supporting both clean fresh initialization and transparent restoration from a checkpoint.
- **Equivalence & Determinism**: Verified in `tests/test_checkpoint_equivalence.py` across single-station and multi-station blocking-after-service scenarios; uninterrupted and checkpointed/resumed runs produce identical summaries, result hashes, and event ordering.
- **Compatibility Diagnostics**: Incompatible schema version, kernel version, configuration hash, model hash, or plugin metadata are rejected with descriptive `IncompatibleCheckpointError` diagnostics.
- **Atomic Writes**: Implemented in `save_checkpoint` using temporary files, fsync, and atomic replace, with SHA-256 payload checksum integrity verification to prevent corrupt or partial files from appearing valid.
- **CLI Subcommands**: Thin `inspect` and `resume` subcommands added to `src/industrialsim/cli.py` exposing the Application API with machine-readable JSON outputs and standard exit codes.

