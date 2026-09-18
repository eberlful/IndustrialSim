# 01: Run one Production Unit deterministically

**What to build:** Enable a user to validate and run a minimal YAML-defined Episode in which one Production Unit passes through one Station and reaches a terminal state with a machine-readable summary. This slice establishes the CPython 3.14 baseline, the smallest explicit-state event kernel, the shared Application API, and thin CLI access without introducing later production features.

**Blocked by:** None (can start immediately).

Status: resolved

- [x] The supported runtime is constrained to CPython 3.14 and the project can be installed and tested from a clean environment.
- [x] A strict YAML configuration describes a minimal Episode, Production Unit, Station, Operation, start time, and end condition; unknown fields fail validation.
- [x] Simulation time uses integer nanoseconds and scheduled events are ordered by time, priority, and monotonic sequence.
- [x] The Application API validates and runs the Episode without exposing kernel internals.
- [x] Thin `validate` and `run` CLI commands expose the same behavior with machine-readable success and failure output.
- [x] Repeating the same configuration and seed produces the same summary and deterministic result hash.
- [x] Tests exercise the complete configuration-to-summary path plus property tests for monotonic time and stable tie-breaking.

## Answer

Issue 01 has been fully implemented and verified:
- **CPython 3.14 runtime constraint**: Constrained in `pyproject.toml` (`requires-python = ">=3.14, <3.15"`) and enforced on module initialization in `src/industrialsim/__init__.py`.
- **Event Kernel**: Implemented in `src/industrialsim/kernel.py` with integer nanosecond time, priority ordering (`EventPriority`), and monotonic sequence counter. Verified with unit tests and Hypothesis property-based tests for monotonic time and stable tie-breaking.
- **Strict YAML Configuration**: Implemented in `src/industrialsim/config.py` using Pydantic models with `extra="forbid"`, duration normalization to integer nanoseconds, and schema validation.
- **Domain Entities & Application API**: Implemented in `src/industrialsim/domain.py` and `src/industrialsim/application.py`. The `validate_config` and `run_episode` functions provide public validation and execution, returning `ValidationResult` and `EpisodeSummary` without exposing kernel internals.
- **CLI Commands**: Implemented in `src/industrialsim/cli.py` exposing thin `validate` and `run` subcommands with machine-readable JSON outputs and standard exit codes (0 for success, 1 for failure).
- **Determinism**: Verified repeated executions produce identical summaries and SHA-256 result hashes.


