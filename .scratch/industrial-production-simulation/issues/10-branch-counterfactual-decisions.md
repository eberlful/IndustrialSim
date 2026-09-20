# 10: Branch counterfactual decisions from a Checkpoint

**What to build:** At a Decision Batch, create at least two isolated Counterfactual Branches from the same Checkpoint, apply different Actions, and compare their outcomes under controlled common randomness.

**Blocked by:** 03: Resume an Episode from a portable Checkpoint; 08: Pause on a Decision Batch and recover by Fallback Policy.

Status: resolved

- [x] The Application API and thin `branch` CLI accept a Decision Checkpoint and at least two alternative Action sets.
- [x] Each Counterfactual Branch has a deterministic identity derived from stable experiment inputs and its Action identity.
- [x] Named Philox streams use semantic keys including stream kind, entity, failure mode, and occurrence index.
- [x] An extra random draw in one Branch does not shift unrelated external random outcomes in another Branch.
- [x] Branch state is isolated: mutation in one continuation cannot affect its parent or siblings.
- [x] Sequential execution of the same alternatives produces identical Branch summaries and hashes on repetition.
- [x] Comparison output reports Actions, raw outcome metrics, hard-constraint outcomes, and provenance for every Branch.

## Answer

Issue 10 has been fully implemented across random generation, engine execution, branching coordinator, comparison reporting, CLI, and automated test suites:

1. **Application API (`branch_checkpoint`) & Thin CLI (`branch`)**:
   - `branch_checkpoint` in `src/industrialsim/application.py` takes a Decision Checkpoint (file path, dict, or `Checkpoint` instance) and a sequence of alternative Action sets, validating that at least two alternative sets are provided.
   - Verifies the checkpoint is at an active Decision Batch (has pending decision requests).
   - Thin CLI `branch` in `src/industrialsim/cli.py` accepts `checkpoint_path` and 2 or more action JSON files (via `nargs="+"`), running `branch_checkpoint` and writing a structured JSON comparison result.

2. **Deterministic Branch Identity**:
   - `_derive_branch_id` computes a stable 16-character SHA-256 hex digest combining `config_hash`, `root_seed`, `simulated_time_ns`, and canonically sorted JSON representations of the branch actions.
   - Sorting action representations guarantees order invariance when multiple actions are supplied in an alternative set.

3. **Philox Random Streams with Semantic Addressing (ADR 0002)**:
   - Added `format_semantic_key` and `get_semantic_key` in `src/industrialsim/random.py` using `stream_kind`, `entity_id`, `failure_mode`, and `occurrence_index`.
   - `SemanticRandomStream.draw_float` supports explicit or auto-incrementing occurrence indexing.
   - Separate streams remain mathematically decoupled under Philox: extra draws in one stream or branch do not advance or alter unrelated draws in another branch.

4. **Isolated Branch State & Execution**:
   - Each alternative branch restores a fresh `EpisodeEngine` instance from the checkpoint with isolated state and copied occurrence counters (`engine.random_occurrence_counters = dict(cp.random_occurrence_counters)`).
   - Mutations in one branch cannot affect the parent checkpoint or sibling branches.
   - Actions are validated and applied to the formed Decision Batch before running each branch continuation to completion.

5. **Bit-for-Bit Determinism on Repetition**:
   - Sequential execution of the same alternatives produces identical branch summaries and identical `result_hash` values on repeat runs.

6. **Comparison Output Contract**:
   - Defined `CounterfactualBranchResult` and `BranchComparisonResult` containing:
     - `branch_id`: Deterministic branch identifier.
     - `actions`: Applied actions (or fallback actions if validation fails).
     - `provenance`: Typed `DecisionProvenance` preserving `provider_id`, `model_id`, and `prompt_id`.
     - `raw_metrics`: Dictionary containing `good_output`, `lead_time_ns`, `wip`, `scrap`, `downtime_ns`, `lateness_ns`, `resource_utilization`, and `total_strategic_cost`. Lead time and lateness calculations strictly exclude scrapped units.
     - `hard_constraints`: Satisfied flag, list of violations (aborts, buffer capacity breaches), and abort status/reasons.
     - `summary` & `result_hash`: Full episode summary and deterministic hash.

7. **Verification & Testing**:
   - `tests/test_random.py`: Semantic key formatting and Philox stream decoupling verification.
   - `tests/test_branch_counterfactual_decisions_e2e.py`: End-to-end testing covering multi-way branching, deterministic branch IDs, action order invariance, parent and sibling isolation, common randomness non-shifting, sequential repeatability, metric accuracy (excluding scrap), fallback handling, and requirement of at least 2 alternatives.
   - `tests/test_cli.py`: CLI invocation tests for valid branching and rejection of fewer than 2 action files.
