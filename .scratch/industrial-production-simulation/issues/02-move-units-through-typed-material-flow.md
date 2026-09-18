# 02: Move Production Units through typed material flow

**What to build:** Let a modeler define Plant, Area, Hall, typed material-flow nodes, routes, and bounded Buffers, then run Production Units through that topology. The delivered scenario visibly demonstrates capacity constraints and blocking-after-service rather than merely validating graph data structures.

**Blocked by:** 01: Run one Production Unit deterministically.

Status: resolved

- [x] Strict configuration represents the Plant location hierarchy independently from the directed Material Flow Graph.
- [x] The graph supports typed Ports, sources, sinks, cycles, parallel routes, and stable human-readable IDs.
- [x] Validation rejects incompatible Ports, duplicate IDs, unreachable required sinks, and invalid source or sink definitions with actionable errors.
- [x] Every Production Unit remains at exactly one node, in one transport placeholder, or in a terminal state throughout a run.
- [x] A bounded Buffer creates observable backpressure and blocking-after-service when downstream capacity is unavailable.
- [x] Optional Station output capacity can relieve the Station while preserving all material-location invariants.
- [x] An Application-level scenario proves end-to-end movement, blocking, unblocking, and terminal completion.

## Answer

Issue 02 has been fully implemented and verified:
- **Plant Location Hierarchy & Material Flow Graph**: Represented independently in `src/industrialsim/config.py` and `src/industrialsim/material_flow.py` with `Plant -> Area -> Hall` and a directed multigraph supporting Sources, Stations, Buffers, Sinks, typed Ports, routes, cycles, and parallel routes.
- **Topology Validation**: Implemented in `MaterialFlowGraph.validate()`. Rejects incompatible port types along routes, duplicate IDs, unreachable sinks, disconnected sources, and invalid port definitions with descriptive actionable error messages.
- **Unit Location Invariant**: Enforced across all state transitions (`RELEASED`, `IN_STATION`, `IN_BUFFER`, `IN_TRANSPORT`, `BLOCKED`, `TERMINAL`), ensuring every unit is always at exactly one node, in one transport route, or in a terminal state.
- **Backpressure & Blocking-After-Service**: Verified in `tests/test_material_flow_simulation.py` with a multi-node scenario where a bounded buffer and slower downstream station cause observable upstream blocking-after-service (`total_blocked_time_ns` tracked).
- **Station Output Capacity**: Relieves the main station processing area when configured, allowing subsequent operations to start while holding finished units in the station output buffer.
- **CLI & Application Integration**: Tested via `validate` and `run` commands in `src/industrialsim/cli.py` and Application API in `src/industrialsim/application.py`. Example scenario added at `examples/material_flow_blocking.yaml`.


