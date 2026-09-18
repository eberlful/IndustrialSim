# Build a small explicit-state event kernel

V1 uses CPython 3.14, constrained to the 3.14 minor release, and a purpose-built discrete-event kernel whose queue contains only serializable records identified by stable event-type IDs. The kernel exposes stepping, bounded running, snapshot, and restore operations and excludes generators, closures, callbacks, and domain objects from persisted state; SimPy is rejected as the production kernel because its generator-based processes obstruct portable versioned checkpoints and inexpensive counterfactual branching.

