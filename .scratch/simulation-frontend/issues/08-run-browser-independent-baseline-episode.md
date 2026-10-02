# 08: Run a Baseline Episode independently of the browser

**What to build:** Start a valid loaded model with the BaselineDecisionProvider, keep its Episode in the local service, and inspect the outcome without tying execution to browser lifetime.

**Blocked by:** 01: Open a local project and display a Plant.

**Status:** ready-for-agent

- [x] Before worker/service wiring, add the required public application-session lifecycle operations alongside existing application APIs, preserving their behavior and regression checks.
- [x] The user can start valid loaded configuration with Baseline; invalid configuration is rejected by the existing authoritative validator.
- [x] The service owns one Episode and a worker serializes mutations; HTTP/UI remain responsive while simulation computes as fast as possible.
- [x] Starting freezes a semantic snapshot of Episode inputs; subsequent source/draft changes cannot alter the active Episode.
- [x] A second start while an Episode is active is rejected without replacing it; closing and reopening the browser attaches to the same session.
- [x] Completed execution produces an initial outcome view and a unique result directory with existing manifest, audit, summary and telemetry semantics.
- [x] The additive session lifecycle separates intermediate advancement from finalization, so later snapshot reads and control commands need not create duplicate terminal records.
- [x] Public-session execution matches direct application execution for the same configuration, seed and action sequence; existing complete and incomplete outputs are never overwritten.
- [x] A browser workflow starts an Episode, reconnects to it and inspects the completed outcome; lifecycle checks verify that a second start does not replace the first.

## Comments

Added public `EpisodeSession` lifecycle operations before worker wiring: frozen inputs,
bounded advancement at settled simulation-time boundaries, isolated observations,
explicit idempotent finalization and incomplete-output closure. Existing engine,
checkpoint and complete-execution APIs retain their outcome behavior. Intermediate
observations project resource metrics on copies, avoiding changes to Machine health
and preserving direct-execution result hashes.

A single serialized `EpisodeWorker` owns execution in the loopback service. Start
validates the current project draft and freezes its inputs; a second active start
is rejected. Published state is independent of browser lifetime. Each Episode
reserves a unique project-local result directory without reusing completed or
incomplete outputs. Finalization writes existing manifest, audit, summary,
resolved configuration, final Checkpoint and configured telemetry artifacts.
Service shutdown stops at a settled boundary and keeps unfinished work visibly
incomplete. The UI starts Baseline, reconnects, displays progress and an initial
outcome with raw metrics and result location; subsequent model edits apply to the
next Episode.

Public lifecycle checks verify direct Baseline equivalence (including the reference
Plant with decisions), exact output/audit/telemetry behavior, idempotent reads and
finalization, time limits, immutable inputs and non-overwriting output reservation.
Worker checks cover validation, second-start rejection, frozen draft inputs and
unique outcomes. Browser acceptance starts, closes and reconnects, checks the
second-start and invalid-draft HTTP gates, and inspects completion. A regression
also protects imported inputs from a delayed initial project read.

Full Python suite: 307 passed, 1 skipped. TypeScript build/typecheck and Python
checks for changed application/service/worker modules pass. Existing unrelated
workspace edits are retained outside this commit.

Final full browser suite: 15 passed. Code review against `09f8811` reports
Standards: 0 findings; Spec: 0 findings. Both reviewers confirmed the lifecycle,
service ownership, frozen inputs, output preservation and reproducibility behavior.
