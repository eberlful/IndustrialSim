# 03: Resume an Episode from a portable Checkpoint

**What to build:** Allow a user to snapshot a running Episode, persist the complete continuation state, inspect its metadata, and resume it in a fresh process with the same externally visible result as an uninterrupted run.

**Blocked by:** 01: Run one Production Unit deterministically.

Status: ready-for-agent

- [ ] A Checkpoint contains schema and kernel versions, model and configuration hashes, simulation time, next sequence, event queue, explicit domain state, root seed, and random occurrence counters.
- [ ] Persisted events and state contain data records only and do not depend on generators, closures, callbacks, or live objects.
- [ ] The Application API can create, serialize, inspect, restore, and continue a Checkpoint.
- [ ] Thin `resume` and Checkpoint-oriented `inspect` CLI behavior uses the same Application API.
- [ ] An uninterrupted run and a checkpointed/resumed run produce identical summaries, result hashes, and observable event order.
- [ ] Incompatible schema, kernel, model, configuration, or plugin metadata is rejected with a specific diagnostic.
- [ ] Checkpoint writes cannot leave a partial file that appears valid.

