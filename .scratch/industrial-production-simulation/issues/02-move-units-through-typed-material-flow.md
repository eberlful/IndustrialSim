# 02: Move Production Units through typed material flow

**What to build:** Let a modeler define Plant, Area, Hall, typed material-flow nodes, routes, and bounded Buffers, then run Production Units through that topology. The delivered scenario visibly demonstrates capacity constraints and blocking-after-service rather than merely validating graph data structures.

**Blocked by:** 01: Run one Production Unit deterministically.

Status: ready-for-agent

- [ ] Strict configuration represents the Plant location hierarchy independently from the directed Material Flow Graph.
- [ ] The graph supports typed Ports, sources, sinks, cycles, parallel routes, and stable human-readable IDs.
- [ ] Validation rejects incompatible Ports, duplicate IDs, unreachable required sinks, and invalid source or sink definitions with actionable errors.
- [ ] Every Production Unit remains at exactly one node, in one transport placeholder, or in a terminal state throughout a run.
- [ ] A bounded Buffer creates observable backpressure and blocking-after-service when downstream capacity is unavailable.
- [ ] Optional Station output capacity can relieve the Station while preserving all material-location invariants.
- [ ] An Application-level scenario proves end-to-end movement, blocking, unblocking, and terminal completion.

