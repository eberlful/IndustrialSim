# 07: Dispatch Transport Orders with shared vehicles

**What to build:** Move Production Units between material-flow nodes through explicit Transport Orders that compete for a configured vehicle pool and route capacity, using a deterministic baseline Dispatch Policy.

**Blocked by:** 02: Move Production Units through typed material flow; 04: Allocate Machines and Workers atomically.

Status: ready-for-agent

- [ ] A required inter-node movement creates a visible Transport Order rather than an implicit delay.
- [ ] Vehicles, vehicle capabilities, shared pools, travel durations, and route capacities are configurable resources.
- [ ] The baseline Dispatch Policy chooses the nearest available suitable vehicle and a shortest admissible route with deterministic tie-breaking.
- [ ] Competing Transport Orders queue without exceeding vehicle or route capacity.
- [ ] Alternative routes can be selected when admissible, and congestion or vehicle scarcity creates observable logistics backpressure.
- [ ] A Production Unit is in exactly one transport while moving and cannot simultaneously occupy a graph node.
- [ ] Application-level tests cover vehicle contention, route contention, alternative routing, arrival, and reproducible ordering.

