# 01: Run one Production Unit deterministically

**What to build:** Enable a user to validate and run a minimal YAML-defined Episode in which one Production Unit passes through one Station and reaches a terminal state with a machine-readable summary. This slice establishes the CPython 3.14 baseline, the smallest explicit-state event kernel, the shared Application API, and thin CLI access without introducing later production features.

**Blocked by:** None (can start immediately).

Status: ready-for-agent

- [ ] The supported runtime is constrained to CPython 3.14 and the project can be installed and tested from a clean environment.
- [ ] A strict YAML configuration describes a minimal Episode, Production Unit, Station, Operation, start time, and end condition; unknown fields fail validation.
- [ ] Simulation time uses integer nanoseconds and scheduled events are ordered by time, priority, and monotonic sequence.
- [ ] The Application API validates and runs the Episode without exposing kernel internals.
- [ ] Thin `validate` and `run` CLI commands expose the same behavior with machine-readable success and failure output.
- [ ] Repeating the same configuration and seed produces the same summary and deterministic result hash.
- [ ] Tests exercise the complete configuration-to-summary path plus property tests for monotonic time and stable tie-breaking.

