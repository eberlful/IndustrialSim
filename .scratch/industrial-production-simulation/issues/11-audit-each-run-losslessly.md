# 11: Audit each run losslessly

**What to build:** Produce a crash-conscious, non-overwriting run artifact set that lets a user inspect and reproduce an Episode or Counterfactual comparison, with a canonical ordered JSONL record of every critical lifecycle and decision event.

**Blocked by:** 09: Expose production-control Actions to a Decision Provider; 10: Branch counterfactual decisions from a Checkpoint.

Status: ready-for-agent

- [ ] Each run writes to a new atomic result location and never overwrites a prior completed run.
- [ ] The result contains a manifest, resolved configuration, ordered JSONL audit log, Checkpoints, and summary with stable relationships between parent and Branch artifacts.
- [ ] The manifest records runtime, library, schema, kernel, model, configuration, plugin, seed, and calibration metadata needed to assess reproducibility.
- [ ] The audit log losslessly records Decision Requests, Actions, validation outcomes, Fallbacks, rewards, failures, and Production Unit lifecycle transitions.
- [ ] Audit records are ordered deterministically and correlate Episode, Branch, Batch, entities, and provider provenance.
- [ ] Interrupted writes remain visibly incomplete and cannot be mistaken for a successful run.
- [ ] The `inspect` behavior summarizes completed and incomplete artifacts through the Application API and CLI.
- [ ] Replay-oriented tests prove critical records are never dropped or reordered under load.

