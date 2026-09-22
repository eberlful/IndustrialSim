# 16: Parallelize Counterfactual Branches and benchmark V1

**What to build:** Run two to eight Counterfactual Branches in isolated worker processes and provide repeatable Scheduler and reference-Plant benchmarks that demonstrate the agreed V1 scale without weakening single-Branch determinism.

**Blocked by:** 10: Branch counterfactual decisions from a Checkpoint; 15: Run and compare the reference automotive Plant.

Status: resolved

- [x] Counterfactual workers receive serialized Checkpoint data and do not rely on platform-specific process memory snapshots.
- [x] Every Branch remains internally single-threaded and isolated from parent and sibling state.
- [x] Sequential and worker-process execution of the same Branch set produce identical summaries, artifacts, and result hashes.
- [x] Failures in one worker are surfaced as structured Branch failures without corrupting successful siblings.
- [x] The `benchmark` Application behavior and CLI expose machine-readable timing, workload, runtime, and reference-hardware metadata.
- [x] A Scheduler benchmark processes five million simple events in under 60 seconds on documented reference hardware.
- [x] A reference-Plant benchmark simulates a production week with 100 to 500 active resources and several million events in under 60 seconds on documented reference hardware.
- [x] Benchmark runs verify determinism across repetitions and do not count multi-process speedup toward the single-Branch target.

## Answer

Issue 16 has been fully implemented across parallel counterfactual branching, structured worker failure handling, benchmark engine, CLI integration, and automated test suites:

1. **Parallel Worker Branching (`branch_checkpoint` with `--workers`)**:
   - `branch_checkpoint` accepts `workers: int = 1` and dispatches branches to isolated worker processes via `concurrent.futures.ProcessPoolExecutor` using `multiprocessing.get_context("spawn")`.
   - Worker processes receive portable serialized checkpoint data (`serialize_checkpoint(cp)`) and configuration data, avoiding any reliance on platform-specific process memory snapshots (fork/shared memory).
   - Each branch executes internally single-threaded and fully isolated from parent and sibling states.
   - Sequential and worker-process execution produce identical summaries, artifacts, and deterministic result hashes (`test_parallel_branch_execution_matches_sequential`).

2. **Structured Worker Failure Isolation**:
   - `CounterfactualBranchResult` has been extended with `status: str = "completed" | "failed"`, `error: str | None`, and nullable `summary: EpisodeSummary | None`.
   - Failures during worker execution or crashes of a worker process are captured and surfaced as structured branch failures with `hard_constraints["aborted"] = True` without corrupting successful sibling branches (`test_parallel_branch_worker_failure_is_structured_and_preserves_siblings`).

3. **Benchmark Suite (`industrialsim.benchmark` & `industrialsim benchmark`)**:
   - `collect_hardware_metadata()` collects machine architecture, CPU count, processor, CPU model, memory, and documented reference hardware specifications.
   - `run_scheduler_benchmark()` benchmarks 5,000,000 simple events on `EventKernel` in ~9 seconds (well under 60 seconds) on reference hardware, verifying determinism across repetitions single-threaded.
   - `run_reference_plant_benchmark()` simulates a production week (120h) with 205 active resources (50 stations, 50 buffers, 50 machines, 50 workers, 5 vehicles) in under 60 seconds, verifying repeatability and determinism across repetitions single-threaded.
   - `run_benchmark()` produces a unified `BenchmarkReport` with machine-readable timing, workload, runtime, and reference-hardware metadata, writing `benchmark_report.json`.
   - Thin CLI `industrialsim benchmark` exposes `--target`, `--scheduler-events`, `--plant-events`, `--repetitions`, and `--output-dir`.
