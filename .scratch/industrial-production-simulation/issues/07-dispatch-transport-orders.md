# 07: Dispatch Transport Orders with shared vehicles

**What to build:** Move Production Units between material-flow nodes through explicit Transport Orders that compete for a configured vehicle pool and route capacity, using a deterministic baseline Dispatch Policy.

**Blocked by:** 02: Move Production Units through typed material flow; 04: Allocate Machines and Workers atomically.

Status: resolved

- [x] A required inter-node movement creates a visible Transport Order rather than an implicit delay.
- [x] Vehicles, vehicle capabilities, shared pools, travel durations, and route capacities are configurable resources.
- [x] The baseline Dispatch Policy chooses the nearest available suitable vehicle and a shortest admissible route with deterministic tie-breaking.
- [x] Competing Transport Orders queue without exceeding vehicle or route capacity.
- [x] Alternative routes can be selected when admissible, and congestion or vehicle scarcity creates observable logistics backpressure.
- [x] A Production Unit is in exactly one transport while moving and cannot simultaneously occupy a graph node.
- [x] Application-level tests cover vehicle contention, route contention, alternative routing, arrival, and reproducible ordering.

## Answer

Issue 07 has been fully implemented across configuration, domain models, dispatch policies, discrete-event simulation engine, portable checkpoints, and testing:

1. **Visible Transport Orders & Inter-Node Movements (ADR 0012, ADR 0014)**:
   - When a Production Unit is released or finishes at a station/buffer, an explicit `TransportOrder` entity is created (`state=PENDING`) and tracked under `domain.transport_orders` and `pending_transport_orders`.
   - Replaced implicit transit timers with explicit multi-phase lifecycles (`PENDING` -> `DISPATCHED` -> `IN_TRANSIT` -> `COMPLETED`/`CANCELLED`), capturing timestamps (`created_time_ns`, `dispatched_time_ns`, `pickup_time_ns`, `completed_time_ns`), assigned `vehicle_id`, and `route_id`.
   - Summaries expose full transport order histories via `TransportOrderSummary` in `SimulationSummary`.

2. **Configurable Resources & Shared Vehicle Pools**:
   - `RouteConfig`: Added `capacity: int | None = None` (defaults to unconstrained), `required_capabilities: list[str]`, and `pool_id: str | None`.
   - `VehiclePoolConfig`: Configurable pools with `id`, `capabilities`, `speed_multiplier`, and description.
   - `VehicleConfig`: Specific vehicles with `id`, `initial_location`, `pool_id`, `capabilities`, and `speed_multiplier` (inheriting pool attributes when unspecified).
   - Validation ensures positive speeds, valid node references, and pool reference integrity.

3. **Deterministic Baseline Dispatch Policy (ADR 0012)**:
   - Implemented `BaselineDispatchPolicy` (`src/industrialsim/dispatch.py`), matching pending orders to vehicles and routes:
     - Uses `DispatchContext` parameter object to encapsulate routing context and eliminate data clumps.
     - Only considers admissible candidate routes respecting process plans, quality rework rules, and downstream node capacity (`_can_accept`).
     - Enforces total route capacity limits (`active_route_occupancy + reserved_route_occupancy < route.capacity`).
     - Selects vehicles satisfying route capability constraints and pool memberships.
     - Calculates shortest graph repositioning distance using Dijkstra pathfinding on `MaterialFlowTopology`.
     - Prioritizes shortest admissible route (`r.transit_time_ns`), then nearest suitable vehicle (`effective_pickup_time` scaled by `v.speed_multiplier`), with deterministic tie-breaking on `(r.id, v.id)`.
     - Supports unconstrained fallback when no vehicles are configured, ensuring 100% backward compatibility.

4. **Contention, Queuing, and Observable Logistics Backpressure**:
   - Competing orders queue deterministically in FIFO order when vehicles or routes are at capacity.
   - If multiple routes lead to admissible targets, the policy routes around congested or occupied routes to alternative admissible routes.
   - Separated `active_route_occupancy` (units physically occupying the route in transit) from `reserved_route_occupancy` (orders dispatched while vehicle is repositioning to pickup), preventing premature route occupancy while maintaining hard capacity limits.
   - Vehicle scarcity and route congestion stall departure from upstream stations and buffers, causing station blocking (`is_blocked=True`, `blocked_unit_id`) and upstream starvation.

5. **Single-Occupancy & Node Disjointness Invariant**:
   - A unit is removed from its source node upon vehicle pickup (`_remove_unit_from_node` called via `_begin_transport`), ensuring it does not occupy a node while in transport.
   - The unit transitions to `ProductionUnitState.IN_TRANSPORT` with its location set to the route ID.
   - Upon arrival at the destination node (`ARRIVAL_AT_NODE`), the unit is handed over to the destination node and the vehicle transitions to `IDLE` (or picks up another order).
   - A Production Unit is in exactly one transport while moving and never simultaneously in a buffer or station.

6. **Checkpointing & Bit-for-Bit Determinism (ADR 0009)**:
   - Added `VehicleSnapshot` and `TransportOrderSnapshot` to `DomainStateSnapshot`.
   - Preserved `active_route_occupancy` and `reserved_route_occupancy` in checkpoint state.
   - Updated `compute_model_hash` to include vehicle and transport order states.
   - Serialized state maintains deterministic ordering with zero-padded order IDs (`to-000001`) and sorted summary outputs, ensuring resumed runs match uninterrupted runs bit-for-bit.

7. **Verification & Testing**:
   - Added comprehensive test suites:
     - `tests/test_vehicle_config.py`: Configuration and validation.
     - `tests/test_vehicle_domain.py`: State transitions, speed, metrics, and utilization.
     - `tests/test_dispatch_policy.py`: Vehicle matching, capability requirements, route capacity, DispatchContext, shortest route priority, speed multiplier, and deterministic tie-breaking.
     - `tests/test_transport_orders_simulation.py`: End-to-end vehicle contention, backpressure, route contention, alternative routing, and checkpoint/resume equivalence.
   - All 129 tests pass (`uv run pytest`) and type checks pass cleanly (`uv run mypy src tests`).


