# 12: Export metrics, Reward, and Parquet telemetry

**What to build:** Give analysts raw production metrics, a transparent configurable scalar Reward, runtime-selectable snapshots, and efficient closed Parquet fragments without making optional telemetry part of the simulation's correctness path.

**Blocked by:** 11: Audit each run losslessly.

Status: resolved

- [x] The run reports raw good output, lead time, WIP, Scrap, downtime, lateness, and resource-utilization metrics without embedded objective weights.
- [x] A configured Reward Policy normalizes selected components and exposes every weight in the resolved experiment configuration.
- [x] Hard-constraint violations remain separate from scalar Reward and can independently terminate an Episode.
- [x] State telemetry can be enabled or disabled at runtime and sampled at configured intervals and domain events.
- [x] Optional telemetry obeys an explicit backpressure policy that may thin samples but cannot drop critical audit records.
- [x] Metrics and training records are written in bounded batches to closed, rotating Parquet fragments with stable schemas.
- [x] Parquet content is demonstrably derived from canonical run data, and incomplete fragments are not advertised as complete datasets.
- [x] Tests verify metrics, Warm-up exclusion, Reward calculation, sampling, thinning, fragment rotation, and schema stability through observable artifacts.

## Answer

Issue 12 is fully implemented and verified:
1. **Raw Production Metrics & Warm-up Exclusion (`src/industrialsim/application.py`):**
   - Added `warm_up_time` / `warm_up_time_ns` to `EpisodeConfig`.
   - `_compute_raw_metrics` and `_compute_current_metrics` compute raw good output, lead time, WIP, scrap, downtime, lateness, and resource utilization across machines, workers, and vehicles, cleanly excluding pre-warmup terminal transitions without embedding objective trade-off weights.
2. **Transparent Reward Policy (`src/industrialsim/config.py`, `src/industrialsim/application.py`):**
   - Configured `RewardPolicyConfig` with `RewardComponentConfig` supporting `weight`, `scale`, `offset`, `target`, and `direction` (`maximize`/`minimize`).
   - Normalizes components dynamically and records transparent `reward` and `reward_breakdown` in `EpisodeSummary`, audit logs, and serialized `resolved_config.yaml`.
3. **Hard Constraints & Independent Termination (`src/industrialsim/config.py`, `src/industrialsim/application.py`):**
   - Added `HardConstraintsConfig` supporting `max_scrap`, `max_downtime_ns`, `max_lead_time_ns`, `enforce_buffer_capacity`, and `terminate_on_violation`.
   - `_check_runtime_hard_constraints` verifies constraints during simulation steps and independently terminates the episode with `hard_constraint_violation` audit log events while keeping scalar reward uncoupled from constraint violations.
4. **State Telemetry Engine & Backpressure (`src/industrialsim/telemetry.py`):**
   - Built `METRICS_TELEMETRY_SCHEMA` and `TRAINING_RECORDS_SCHEMA` using `pyarrow`.
   - Built `TelemetryManager` supporting runtime toggling (`enable()`/`disable()`), configurable sample intervals (`sample_interval_ns`), domain event triggers (`operation_completed`, `decision_batch`, `sink_arrival`, etc.), and backpressure policies (`thin`, `drop_newest`, `drop_oldest`) that thin high-volume telemetry without impacting lossless audit logs.
   - Bounded batch flushing writes to closed rotating fragments (`metrics_fragment_{index:05d}.parquet` and `training_fragment_{index:05d}.parquet`) using atomic `.parquet.tmp` write-and-rename.
5. **Artifact Integration & Incomplete Fragment Protection (`src/industrialsim/audit.py`):**
   - `RunArtifactWriter` and `inspect_run` discover only complete closed Parquet fragments, omitting incomplete `.parquet.tmp` files and advertising closed fragments in `manifest.json`.
   - Full counterfactual branch wiring in `branch_checkpoint` and `EpisodeEngine.restore`.
6. **Verification (`tests/test_telemetry_and_metrics_e2e.py`):**
   - 9 end-to-end tests covering raw metrics reporting with warm-up exclusion, reward normalization, weight exposure, hard constraint termination, runtime telemetry toggling, backpressure thinning vs audit preservation, Parquet fragment rotation, schema stability, incomplete fragment safety, and counterfactual branch Parquet exports.
   - All 192 test suite cases pass cleanly with 100% mypy type checking.
