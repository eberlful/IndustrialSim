# 16: Parallelize Counterfactual Branches and benchmark V1

**What to build:** Run two to eight Counterfactual Branches in isolated worker processes and provide repeatable Scheduler and reference-Plant benchmarks that demonstrate the agreed V1 scale without weakening single-Branch determinism.

**Blocked by:** 10: Branch counterfactual decisions from a Checkpoint; 15: Run and compare the reference automotive Plant.

Status: ready-for-agent

- [ ] Counterfactual workers receive serialized Checkpoint data and do not rely on platform-specific process memory snapshots.
- [ ] Every Branch remains internally single-threaded and isolated from parent and sibling state.
- [ ] Sequential and worker-process execution of the same Branch set produce identical summaries, artifacts, and result hashes.
- [ ] Failures in one worker are surfaced as structured Branch failures without corrupting successful siblings.
- [ ] The `benchmark` Application behavior and CLI expose machine-readable timing, workload, runtime, and reference-hardware metadata.
- [ ] A Scheduler benchmark processes five million simple events in under 60 seconds on documented reference hardware.
- [ ] A reference-Plant benchmark simulates a production week with 100 to 500 active resources and several million events in under 60 seconds on documented reference hardware.
- [ ] Benchmark runs verify determinism across repetitions and do not count multi-process speedup toward the single-Branch target.
