# 11: Audit each run losslessly

**What to build:** Produce a crash-conscious, non-overwriting run artifact set that lets a user inspect and reproduce an Episode or Counterfactual comparison, with a canonical ordered JSONL record of every critical lifecycle and decision event.

**Blocked by:** 09: Expose production-control Actions to a Decision Provider; 10: Branch counterfactual decisions from a Checkpoint.

Status: resolved

- [x] Each run writes to a new atomic result location and never overwrites a prior completed run.
- [x] The result contains a manifest, resolved configuration, ordered JSONL audit log, Checkpoints, and summary with stable relationships between parent and Branch artifacts.
- [x] The manifest records runtime, library, schema, kernel, model, configuration, plugin, seed, and calibration metadata needed to assess reproducibility.
- [x] The audit log losslessly records Decision Requests, Actions, validation outcomes, Fallbacks, rewards, failures, and Production Unit lifecycle transitions.
- [x] Audit records are ordered deterministically and correlate Episode, Branch, Batch, entities, and provider provenance.
- [x] Interrupted writes remain visibly incomplete and cannot be mistaken for a successful run.
- [x] The `inspect` behavior summarizes completed and incomplete artifacts through the Application API and CLI.
- [x] Replay-oriented tests prove critical records are never dropped or reordered under load.

## Answer

Issue 11 is fully implemented and verified:
1. **Audit & Artifact Management (`src/industrialsim/audit.py`):**
   - Added `RunArtifactWriter` with atomic directory initialization, `.incomplete` marker tracking, and overwrite protection (`RunArtifactExistsError`).
   - Implemented `AuditLogger` with deterministic sequential `record_id` and strictly monotonic event stream written to `audit.jsonl`.
   - Built comprehensive reproducibility collectors for `manifest.json`: runtime (Python implementation, version, architecture, OS platform), libraries (`pydantic`, `ruamel.yaml`, `pytest`), calibration (`is_calibrated: false` for synthetic reference defaults), config/model sha256 checksums, kernel version, schema version, root seed.
   - Saves `resolved_config.yaml` using `ruamel.yaml` and finalizes `summary.json`.
   - Built `RunInspection`, `inspect_run(path)`, and unified `inspect(path)` supporting inspection of completed and incomplete run directories as well as checkpoint files.
2. **Lifecycle & Decision Event Hooks (`src/industrialsim/application.py`):**
   - Wired audit event logging into `EpisodeEngine` across all production unit lifecycle transitions (`RELEASED`, `IN_TRANSPORT`, `IN_STATION`, `IN_BUFFER`, `BLOCKED`, `TERMINAL`, scrap), operation starts/completions, quality inspections, machine failures/disruptions, decision requests, applied actions, validation outcomes, fallbacks, abort failures, and rewards.
   - Updated `run_episode` and `branch_checkpoint` with `output_dir` support, generating parent checkpoint, root manifest, comparison summary, and per-branch isolated directories with stable lineage references.
3. **CLI Integration (`src/industrialsim/cli.py`):**
   - Extended `run` and `branch` commands with optional `--output-dir` (defaulting `run` to `./runs/<run_id>`).
   - Unified `inspect` CLI command to inspect both checkpoint files and run artifact directories.
4. **Verification:**
   - 9 end-to-end tests in `tests/test_audit_artifacts_e2e.py` covering atomic directory creation, overwrite protection, incomplete write handling, manifest metadata, lossless ordered logging, fallback logging, branch comparison relationships, CLI/API inspection, and replay under load.
   - 183 total tests passing across entire test suite.
   - 100% typechecked with `mypy src tests` passing with 0 errors.

