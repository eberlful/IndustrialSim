# 10: Branch counterfactual decisions from a Checkpoint

**What to build:** At a Decision Batch, create at least two isolated Counterfactual Branches from the same Checkpoint, apply different Actions, and compare their outcomes under controlled common randomness.

**Blocked by:** 03: Resume an Episode from a portable Checkpoint; 08: Pause on a Decision Batch and recover by Fallback Policy.

Status: ready-for-agent

- [ ] The Application API and thin `branch` CLI accept a Decision Checkpoint and at least two alternative Action sets.
- [ ] Each Counterfactual Branch has a deterministic identity derived from stable experiment inputs and its Action identity.
- [ ] Named Philox streams use semantic keys including stream kind, entity, failure mode, and occurrence index.
- [ ] An extra random draw in one Branch does not shift unrelated external random outcomes in another Branch.
- [ ] Branch state is isolated: mutation in one continuation cannot affect its parent or siblings.
- [ ] Sequential execution of the same alternatives produces identical Branch summaries and hashes on repetition.
- [ ] Comparison output reports Actions, raw outcome metrics, hard-constraint outcomes, and provenance for every Branch.

