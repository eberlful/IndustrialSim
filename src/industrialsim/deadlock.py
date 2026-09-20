from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Any, Sequence, TYPE_CHECKING

if TYPE_CHECKING:
    from industrialsim.application import EpisodeEngine
    from industrialsim.domain import ProductionUnit
    from industrialsim.config import RouteConfig


@dataclass(frozen=True)
class WaitEdge:
    from_entity: str
    to_entity: str
    resource: str
    wait_type: str
    holder: str | None = None
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "from_entity": self.from_entity,
            "to_entity": self.to_entity,
            "waiter": self.from_entity,
            "holder": self.holder if self.holder is not None else self.to_entity,
            "resource": self.resource,
            "wait_type": self.wait_type,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class DeadlockDiagnosis:
    deadlock_type: str
    involved_entities: list[str]
    capacities: dict[str, dict[str, Any]]
    ownership: dict[str, list[str]]
    wait_edges: list[dict[str, Any]]
    cycle: list[str]
    reason: str
    simulated_time_ns: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "deadlock_type": self.deadlock_type,
            "involved_entities": list(self.involved_entities),
            "capacities": {k: dict(v) for k, v in self.capacities.items()},
            "ownership": {k: list(v) for k, v in self.ownership.items()},
            "wait_edges": [dict(e) for e in self.wait_edges],
            "cycle": list(self.cycle),
            "reason": self.reason,
            "simulated_time_ns": self.simulated_time_ns,
        }


@dataclass
class WaitForGraph:
    nodes: set[str] = field(default_factory=set)
    edges: list[WaitEdge] = field(default_factory=list)
    adjacency: dict[str, list[WaitEdge]] = field(default_factory=dict)

    def add_edge(self, edge: WaitEdge) -> None:
        self.nodes.add(edge.from_entity)
        self.nodes.add(edge.to_entity)
        self.edges.append(edge)
        self.adjacency.setdefault(edge.from_entity, []).append(edge)


def _collect_active_finite_entities(engine: EpisodeEngine) -> set[str]:
    """Collect IDs of entities currently actively performing finite operations, in transit, or undergoing maintenance."""
    active_entities: set[str] = set()

    # Active operations on stations
    for st_id, op_info in engine.active_operations.items():
        tok = op_info.get("token")
        if isinstance(tok, int) and tok > 0:
            active_entities.add(st_id)
            if op_info.get("unit_id"):
                active_entities.add(op_info["unit_id"])
            for m_id in op_info.get("machines", []):
                active_entities.add(m_id)
            for w_alloc in op_info.get("workers", []):
                active_entities.add(w_alloc["worker_id"])

    # Active maintenances or repairs
    for m_id, maint_info in engine.active_maintenances.items():
        tok = maint_info.get("token")
        if isinstance(tok, int) and tok > 0:
            active_entities.add(m_id)
            for w_alloc in maint_info.get("workers", []):
                active_entities.add(w_alloc["worker_id"])

    # Future planned releases of created units (finite wait)
    created_future_units = {
        u_cfg.id for u_cfg in engine.cfg.production_units
        if u_cfg.release_time_ns > engine.kernel.current_time_ns
    }
    for u_id in created_future_units:
        if u_id in engine.units and str(engine.units[u_id].state) == "created":
            active_entities.add(u_id)

    return active_entities


def _add_dispatch_wait_edges(
    wfg: WaitForGraph,
    engine: EpisodeEngine,
    unit: ProductionUnit,
    candidate_routes: Sequence[RouteConfig],
) -> None:
    """Add wait edges for a unit attempting to dispatch across candidate routes."""
    for r in candidate_routes:
        target_id = r.target_node_id
        # Target node is Buffer
        if target_id in engine.buffers:
            target_b = engine.buffers[target_id]
            if not target_b.can_accept(reserved=engine.in_flight_to[target_id]):
                for occ in target_b.occupants:
                    wfg.add_edge(
                        WaitEdge(
                            from_entity=unit.id,
                            to_entity=target_b.id,
                            resource=target_b.id,
                            wait_type="buffer_capacity",
                            holder=occ,
                            reason=f"Buffer '{target_b.id}' at capacity ({len(target_b.occupants)}/{target_b.capacity}) holding '{occ}'",
                        )
                    )
                    wfg.add_edge(
                        WaitEdge(
                            from_entity=target_b.id,
                            to_entity=occ,
                            resource=target_b.id,
                            wait_type="buffer_occupancy",
                            holder=occ,
                            reason=f"Buffer '{target_b.id}' holds unit '{occ}'",
                        )
                    )
        # Target node is Station
        elif target_id in engine.stations:
            target_st = engine.stations[target_id]
            if not target_st.can_accept(reserved=engine.in_flight_to[target_id]):
                holder = target_st.current_unit_id or target_st.blocked_unit_id
                if holder:
                    wfg.add_edge(
                        WaitEdge(
                            from_entity=unit.id,
                            to_entity=target_st.id,
                            resource=target_st.id,
                            wait_type="station_occupancy",
                            holder=holder,
                            reason=f"Station '{target_st.id}' occupied by '{holder}'",
                        )
                    )
                    wfg.add_edge(
                        WaitEdge(
                            from_entity=target_st.id,
                            to_entity=holder,
                            resource=target_st.id,
                            wait_type="station_hold",
                            holder=holder,
                            reason=f"Station '{target_st.id}' holds unit '{holder}'",
                        )
                    )

        # Route capacity check
        if r.capacity is not None:
            current_occ = engine.active_route_occupancy.get(r.id, 0) + engine.reserved_route_occupancy.get(r.id, 0)
            if current_occ >= r.capacity:
                wfg.add_edge(
                    WaitEdge(
                        from_entity=unit.id,
                        to_entity=r.id,
                        resource=r.id,
                        wait_type="route_capacity",
                        holder=r.id,
                        reason=f"Route '{r.id}' at capacity ({current_occ}/{r.capacity})",
                    )
                )
                # Outgoing edges from route to current traversing vehicles or units
                for v in engine.vehicles.values():
                    if v.current_route_id == r.id:
                        wfg.add_edge(
                            WaitEdge(
                                from_entity=r.id,
                                to_entity=v.id,
                                resource=r.id,
                                wait_type="route_occupancy",
                                holder=v.id,
                                reason=f"Route '{r.id}' traversed by vehicle '{v.id}'",
                            )
                        )
                for ru in engine.units.values():
                    if ru.location == r.id:
                        wfg.add_edge(
                            WaitEdge(
                                from_entity=r.id,
                                to_entity=ru.id,
                                resource=r.id,
                                wait_type="route_occupancy",
                                holder=ru.id,
                                reason=f"Route '{r.id}' occupied by unit '{ru.id}'",
                            )
                        )

        # Vehicle availability check
        if len(engine.vehicles) > 0:
            available_v = [v for v in engine.vehicles.values() if v.is_available()]
            if not available_v:
                for v in engine.vehicles.values():
                    holding_u = v.current_unit_id
                    if not holding_u and v.current_order_id and v.current_order_id in engine.transport_orders:
                        holding_u = engine.transport_orders[v.current_order_id].unit_id
                    holder_id = holding_u or v.id
                    wfg.add_edge(
                        WaitEdge(
                            from_entity=unit.id,
                            to_entity=v.id,
                            resource=v.id,
                            wait_type="vehicle_availability",
                            holder=holder_id,
                            reason=f"Vehicle '{v.id}' unavailable or allocated to '{holder_id}'",
                        )
                    )
                    if holding_u:
                        wfg.add_edge(
                            WaitEdge(
                                from_entity=v.id,
                                to_entity=holding_u,
                                resource=v.id,
                                wait_type="vehicle_allocation",
                                holder=holding_u,
                                reason=f"Vehicle '{v.id}' allocated to unit '{holding_u}'",
                            )
                        )


def build_wait_for_graph(engine: EpisodeEngine) -> WaitForGraph:
    """Build a comprehensive Wait-For Graph across units, buffers, stations, machines, workers, vehicles, and routes."""
    wfg = WaitForGraph()
    active_entities = _collect_active_finite_entities(engine)

    # 1. Unfinished Production Units
    for unit_id, unit in engine.units.items():
        if str(unit.state) in ("terminal", "scrapped") or unit.quality_state == "scrapped":
            continue
        if unit.id in active_entities:
            continue

        loc = unit.location

        # Unit in Buffer
        if loc in engine.buffers:
            buf = engine.buffers[loc]
            # If not at head of buffer, FIFO buffer precedence
            if buf.occupants and buf.occupants[0] != unit.id:
                head_id = buf.occupants[0]
                wfg.add_edge(
                    WaitEdge(
                        from_entity=unit.id,
                        to_entity=head_id,
                        resource=buf.id,
                        wait_type="buffer_precedence",
                        holder=head_id,
                        reason=f"Unit '{unit.id}' held behind '{head_id}' in buffer '{buf.id}'",
                    )
                )
            elif buf.occupants and buf.occupants[0] == unit.id:
                # Unit at head of buffer wants to advance
                candidate_routes = engine._get_candidate_routes_for_unit(buf.id, unit)
                _add_dispatch_wait_edges(wfg, engine, unit, candidate_routes)

        # Unit in Station
        elif loc in engine.stations:
            st = engine.stations[loc]

            # Blocked after service / in output buffer
            if st.is_blocked or st.has_output_units():
                candidate_routes = engine._get_candidate_routes_for_unit(st.id, unit)
                _add_dispatch_wait_edges(wfg, engine, unit, candidate_routes)

            # Waiting for resources in station
            waiter = next((w for w in engine.resource_waiters if w["station_id"] == st.id and w["unit_id"] == unit.id), None)
            if waiter:
                ops_list = list(st.operations.values())
                op = ops_list[waiter["op_index"]]
                # Machines
                for m_id in op.required_machines:
                    mach = engine.machines.get(m_id)
                    if mach and not mach.can_allocate(1, engine.kernel.current_time_ns):
                        holding_op = next((a for a in engine.active_operations.values() if m_id in a["machines"]), None)
                        holding_unit = holding_op["unit_id"] if holding_op else (mach.active_allocations[0]["unit_id"] if mach.active_allocations else None)
                        wfg.add_edge(
                            WaitEdge(
                                from_entity=unit.id,
                                to_entity=mach.id,
                                resource=mach.id,
                                wait_type="machine_allocation",
                                holder=holding_unit,
                                reason=f"Machine '{mach.id}' unavailable or allocated to '{holding_unit}'",
                            )
                        )
                        if holding_unit:
                            wfg.add_edge(
                                WaitEdge(
                                    from_entity=mach.id,
                                    to_entity=holding_unit,
                                    resource=mach.id,
                                    wait_type="machine_hold",
                                    holder=holding_unit,
                                    reason=f"Machine '{mach.id}' held for unit '{holding_unit}'",
                                )
                            )
                # Workers
                for w_req in op.required_workers:
                    req_qual = w_req.get("qualification") if isinstance(w_req, dict) else getattr(w_req, "qualification", None)
                    for worker in engine.workers.values():
                        if req_qual in worker.qualifications and not worker.can_allocate(1, engine.kernel.current_time_ns):
                            holding_unit = worker.active_allocations[0]["unit_id"] if worker.active_allocations else None
                            wfg.add_edge(
                                WaitEdge(
                                    from_entity=unit.id,
                                    to_entity=worker.id,
                                    resource=worker.id,
                                    wait_type="worker_allocation",
                                    holder=holding_unit,
                                    reason=f"Worker '{worker.id}' unavailable or allocated to '{holding_unit}'",
                                )
                            )
                            if holding_unit:
                                wfg.add_edge(
                                    WaitEdge(
                                        from_entity=worker.id,
                                        to_entity=holding_unit,
                                        resource=worker.id,
                                        wait_type="worker_hold",
                                        holder=holding_unit,
                                        reason=f"Worker '{worker.id}' held for unit '{holding_unit}'",
                                    )
                                )

    # 2. Vehicles holding units waiting for destination node capacity
    for v in engine.vehicles.values():
        if v.id in active_entities:
            continue
        order_id = v.current_order_id
        if order_id and order_id in engine.transport_orders:
            order = engine.transport_orders[order_id]
            dest_id = order.target_node_id
            if dest_id in engine.buffers:
                buf = engine.buffers[dest_id]
                if not buf.can_accept(reserved=0):
                    for occ in buf.occupants:
                        wfg.add_edge(
                            WaitEdge(
                                from_entity=v.id,
                                to_entity=buf.id,
                                resource=buf.id,
                                wait_type="buffer_capacity",
                                holder=occ,
                                reason=f"Vehicle '{v.id}' blocked waiting for buffer '{buf.id}' holding '{occ}'",
                            )
                        )
            elif dest_id in engine.stations:
                st = engine.stations[dest_id]
                if not st.can_accept(reserved=0):
                    holder = st.current_unit_id or st.blocked_unit_id
                    if holder:
                        wfg.add_edge(
                            WaitEdge(
                                from_entity=v.id,
                                to_entity=st.id,
                                resource=st.id,
                                wait_type="station_occupancy",
                                holder=holder,
                                reason=f"Vehicle '{v.id}' blocked waiting for station '{st.id}' holding '{holder}'",
                            )
                        )
            # Vehicle waiting for assigned route capacity
            assigned_r = order.assigned_route_id
            if assigned_r and assigned_r in engine.routes_by_id:
                route = engine.routes_by_id[assigned_r]
                if route.capacity is not None:
                    current_occ = engine.active_route_occupancy.get(route.id, 0) + engine.reserved_route_occupancy.get(route.id, 0)
                    if current_occ >= route.capacity:
                        wfg.add_edge(
                            WaitEdge(
                                from_entity=v.id,
                                to_entity=route.id,
                                resource=route.id,
                                wait_type="route_capacity",
                                holder=route.id,
                                reason=f"Vehicle '{v.id}' waiting for route '{route.id}' at capacity ({current_occ}/{route.capacity})",
                            )
                        )

    return wfg


def _find_deterministic_cycle(wfg: WaitForGraph, active_entities: set[str]) -> list[str] | None:
    """Find a cycle deterministically using lexicographically sorted DFS, ignoring active progress entities."""
    sorted_nodes = sorted(wfg.nodes)

    visited: set[str] = set()
    rec_stack: list[str] = []
    rec_set: set[str] = set()

    def dfs(node: str) -> list[str] | None:
        visited.add(node)
        rec_stack.append(node)
        rec_set.add(node)

        outgoing = sorted(wfg.adjacency.get(node, []), key=lambda e: (e.to_entity, e.resource, e.wait_type))
        for edge in outgoing:
            target = edge.to_entity
            if target in active_entities:
                continue

            if target in rec_set:
                cycle_start_idx = rec_stack.index(target)
                cycle = rec_stack[cycle_start_idx:] + [target]
                return cycle

            if target not in visited:
                res = dfs(target)
                if res is not None:
                    return res

        rec_stack.pop()
        rec_set.remove(node)
        return None

    for start_node in sorted_nodes:
        if start_node in active_entities:
            continue
        if start_node not in visited:
            cycle = dfs(start_node)
            if cycle is not None:
                if not any(e in active_entities for e in cycle):
                    return cycle

    return None


def _collect_capacities(engine: EpisodeEngine, involved_entities: Sequence[str]) -> dict[str, dict[str, Any]]:
    """Collect capacity metadata for all entities involved in a deadlock."""
    capacities: dict[str, dict[str, Any]] = {}
    for ent in involved_entities:
        if ent in engine.buffers:
            buf = engine.buffers[ent]
            capacities[ent] = {
                "kind": "buffer",
                "capacity": buf.capacity,
                "occupancy": len(buf.occupants),
            }
        elif ent in engine.stations:
            st = engine.stations[ent]
            capacities[ent] = {
                "kind": "station",
                "capacity": 1,
                "output_capacity": st.output_capacity,
                "output_occupancy": len(st.output_buffer),
                "is_blocked": st.is_blocked,
                "is_busy": st.is_busy,
            }
        elif ent in engine.machines:
            mach = engine.machines[ent]
            capacities[ent] = {
                "kind": "machine",
                "capacity": mach.capacity,
                "allocated": len(mach.active_allocations),
                "is_failed": mach.is_failed,
            }
        elif ent in engine.workers:
            w = engine.workers[ent]
            capacities[ent] = {
                "kind": "worker",
                "capacity": w.capacity,
                "allocated": len(w.active_allocations),
            }
        elif ent in engine.routes_by_id:
            r = engine.routes_by_id[ent]
            capacities[ent] = {
                "kind": "route",
                "capacity": r.capacity if r.capacity is not None else -1,
                "occupancy": engine.active_route_occupancy.get(r.id, 0) + engine.reserved_route_occupancy.get(r.id, 0),
            }
        elif ent in engine.vehicles:
            v = engine.vehicles[ent]
            capacities[ent] = {
                "kind": "vehicle",
                "capacity": 1,
                "is_available": v.is_available(),
                "location": v.location,
            }
    return capacities


def _collect_ownership(engine: EpisodeEngine, involved_entities: Sequence[str]) -> dict[str, list[str]]:
    """Collect unit ownership mapping for all entities involved in a deadlock."""
    ownership: dict[str, list[str]] = {}
    for ent in involved_entities:
        if ent in engine.buffers:
            ownership[ent] = list(engine.buffers[ent].occupants)
        elif ent in engine.stations:
            st = engine.stations[ent]
            holders: list[str] = []
            if st.current_unit_id:
                holders.append(st.current_unit_id)
            if st.blocked_unit_id and st.blocked_unit_id not in holders:
                holders.append(st.blocked_unit_id)
            holders.extend(st.output_buffer)
            ownership[ent] = holders
        elif ent in engine.machines:
            mach = engine.machines[ent]
            ownership[ent] = [a["unit_id"] for a in mach.active_allocations if a.get("unit_id")]
        elif ent in engine.workers:
            w = engine.workers[ent]
            ownership[ent] = [a["unit_id"] for a in w.active_allocations if a.get("unit_id")]
        elif ent in engine.vehicles:
            v = engine.vehicles[ent]
            if v.current_unit_id:
                ownership[ent] = [v.current_unit_id]
            elif v.current_order_id and v.current_order_id in engine.transport_orders:
                ownership[ent] = [engine.transport_orders[v.current_order_id].unit_id]
            else:
                ownership[ent] = []
    return ownership


def analyze_deadlock(engine: EpisodeEngine) -> DeadlockDiagnosis | None:
    """Analyze the current simulation state for unresolved wait relationships and deadlocks."""
    unfinished_units = [
        u for u in engine.units.values()
        if str(u.state) not in ("terminal", "scrapped") and u.quality_state != "scrapped"
    ]
    if not unfinished_units:
        return None

    active_entities = _collect_active_finite_entities(engine)
    wfg = build_wait_for_graph(engine)

    cycle = _find_deterministic_cycle(wfg, active_entities)
    if not cycle:
        return None

    # Determine involved entities from cycle
    cycle_entities_set = set(cycle)
    for ent in list(cycle_entities_set):
        if ent in engine.units:
            u_loc = engine.units[ent].location
            if u_loc in engine.stations or u_loc in engine.buffers:
                cycle_entities_set.add(u_loc)
    involved_entities = sorted(cycle_entities_set)

    # Filter wait edges that are part of the involved cycle
    involved_edges: list[dict[str, Any]] = []
    for edge in wfg.edges:
        if edge.from_entity in cycle_entities_set and edge.to_entity in cycle_entities_set:
            involved_edges.append(edge.to_dict())

    capacities = _collect_capacities(engine, involved_entities)
    ownership = _collect_ownership(engine, involved_entities)

    # Determine deadlock type
    edge_types = {e["wait_type"] for e in involved_edges}
    if any("vehicle" in t or "route" in t for t in edge_types):
        deadlock_type = "logistics_cycle"
    elif any("machine" in t or "worker" in t for t in edge_types):
        deadlock_type = "resource_cycle"
    elif any("buffer" in t for t in edge_types):
        deadlock_type = "buffer_cycle"
    else:
        deadlock_type = "production_deadlock"

    cycle_str = " -> ".join(cycle)
    reason = f"Deadlock detected ({deadlock_type}): unresolved circular wait along {cycle_str}"

    return DeadlockDiagnosis(
        deadlock_type=deadlock_type,
        involved_entities=involved_entities,
        capacities=capacities,
        ownership=ownership,
        wait_edges=involved_edges,
        cycle=cycle,
        reason=reason,
        simulated_time_ns=engine.kernel.current_time_ns,
    )
