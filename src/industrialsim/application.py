from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
from typing import Any, Sequence
from pydantic import ValidationError
from ruamel.yaml import YAML

from industrialsim.config import (
    MaterialFlowConfig,
    NodeConfig,
    PortConfig,
    RouteConfig,
    SimulationConfig,
    StationConfig,
)
from industrialsim.domain import (
    Break,
    Buffer,
    Machine,
    Operation,
    ProductionUnit,
    ProductionUnitState,
    Shift,
    Station,
    Worker,
)
from industrialsim.kernel import EventKernel, EventPriority, ScheduledEvent


_yaml = YAML(typ="safe", pure=True)


@dataclass(frozen=True)
class ValidationResult:
    is_valid: bool
    errors: list[str] = field(default_factory=list)
    config: SimulationConfig | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.is_valid,
            "errors": self.errors,
            "schema_version": self.config.schema_version if self.config else None,
        }


@dataclass(frozen=True)
class ProductionUnitSummary:
    id: str
    variant: str
    quality_state: str
    state: str
    location: str
    history: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "variant": self.variant,
            "quality_state": self.quality_state,
            "state": self.state,
            "location": self.location,
            "history": self.history,
        }


@dataclass(frozen=True)
class StationSummary:
    id: str
    operations_completed: int
    total_busy_time_ns: int
    total_blocked_time_ns: int = 0
    total_waiting_time_ns: int = 0
    interrupted_count: int = 0
    resumed_count: int = 0
    restarted_count: int = 0
    scrapped_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "operations_completed": self.operations_completed,
            "total_busy_time_ns": self.total_busy_time_ns,
            "total_blocked_time_ns": self.total_blocked_time_ns,
            "total_waiting_time_ns": self.total_waiting_time_ns,
            "interrupted_count": self.interrupted_count,
            "resumed_count": self.resumed_count,
            "restarted_count": self.restarted_count,
            "scrapped_count": self.scrapped_count,
        }


@dataclass(frozen=True)
class MachineSummary:
    id: str
    capacity: int
    operations_completed: int
    total_busy_time_ns: int
    total_idle_time_ns: int
    total_break_time_ns: int
    total_off_shift_time_ns: int
    utilization: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "capacity": self.capacity,
            "operations_completed": self.operations_completed,
            "total_busy_time_ns": self.total_busy_time_ns,
            "total_idle_time_ns": self.total_idle_time_ns,
            "total_break_time_ns": self.total_break_time_ns,
            "total_off_shift_time_ns": self.total_off_shift_time_ns,
            "utilization": self.utilization,
        }


@dataclass(frozen=True)
class WorkerSummary:
    id: str
    kind: str
    capacity: int
    qualifications: list[str]
    operations_completed: int
    total_busy_time_ns: int
    total_idle_time_ns: int
    total_break_time_ns: int
    total_off_shift_time_ns: int
    utilization: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "capacity": self.capacity,
            "qualifications": list(self.qualifications),
            "operations_completed": self.operations_completed,
            "total_busy_time_ns": self.total_busy_time_ns,
            "total_idle_time_ns": self.total_idle_time_ns,
            "total_break_time_ns": self.total_break_time_ns,
            "total_off_shift_time_ns": self.total_off_shift_time_ns,
            "utilization": self.utilization,
        }


@dataclass(frozen=True)
class BufferSummary:
    id: str
    capacity: int
    peak_occupancy: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "capacity": self.capacity,
            "peak_occupancy": self.peak_occupancy,
        }


@dataclass(frozen=True)
class EpisodeSummary:
    status: str
    seed: int
    simulated_time_ns: int
    events_processed: int
    production_units: list[ProductionUnitSummary]
    stations: list[StationSummary]
    result_hash: str
    buffers: list[BufferSummary] = field(default_factory=list)
    machines: list[MachineSummary] = field(default_factory=list)
    workers: list[WorkerSummary] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "seed": self.seed,
            "simulated_time_ns": self.simulated_time_ns,
            "events_processed": self.events_processed,
            "production_units": [u.to_dict() for u in self.production_units],
            "stations": [s.to_dict() for s in self.stations],
            "buffers": [b.to_dict() for b in self.buffers],
            "machines": [m.to_dict() for m in self.machines],
            "workers": [w.to_dict() for w in self.workers],
            "result_hash": self.result_hash,
        }


def _parse_yaml_source(source: str | Path | dict[str, Any]) -> dict[str, Any]:
    if isinstance(source, dict):
        return source

    if isinstance(source, Path):
        content = source.read_text(encoding="utf-8")
        parsed = _yaml.load(content)
        if not isinstance(parsed, dict):
            raise ValueError(f"YAML at {source} did not produce a dictionary mapping")
        return parsed

    if isinstance(source, str):
        path = Path(source)
        if path.is_file():
            content = path.read_text(encoding="utf-8")
            parsed = _yaml.load(content)
        else:
            parsed = _yaml.load(source)
        if not isinstance(parsed, dict):
            raise ValueError("YAML content did not produce a dictionary mapping")
        return parsed

    raise TypeError(f"Unsupported source type: {type(source).__name__}")


def validate_config(source: str | Path | dict[str, Any]) -> ValidationResult:
    try:
        raw_dict = _parse_yaml_source(source)
    except Exception as e:
        return ValidationResult(is_valid=False, errors=[f"YAML parsing error: {e}"])

    try:
        cfg = SimulationConfig.model_validate(raw_dict)
        return ValidationResult(is_valid=True, errors=[], config=cfg)
    except ValidationError as e:
        error_messages = [f"{'.'.join(str(loc) for loc in err['loc'])}: {err['msg']}" for err in e.errors()]
        return ValidationResult(is_valid=False, errors=error_messages)
    except ValueError as e:
        return ValidationResult(is_valid=False, errors=[str(e)])


def _compute_result_hash(
    status: str,
    seed: int,
    simulated_time_ns: int,
    events_processed: int,
    units: list[ProductionUnitSummary],
    stations: list[StationSummary],
    buffers: list[BufferSummary] | None = None,
    machines: list[MachineSummary] | None = None,
    workers: list[WorkerSummary] | None = None,
) -> str:
    data: dict[str, Any] = {
        "status": status,
        "seed": seed,
        "simulated_time_ns": simulated_time_ns,
        "events_processed": events_processed,
        "production_units": [u.to_dict() for u in units],
        "stations": [s.to_dict() for s in stations],
        "buffers": [b.to_dict() for b in (buffers or [])],
    }
    if machines:
        data["machines"] = [m.to_dict() for m in machines]
    if workers:
        data["workers"] = [w.to_dict() for w in workers]
    canonical_json = json.dumps(data, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


def _synthesize_minimal_material_flow(stations_cfg: list[StationConfig]) -> MaterialFlowConfig:
    """Unify single-station configs under the material flow engine without code duplication."""
    nodes: list[NodeConfig] = [
        NodeConfig(
            id="src-auto",
            kind="source",
            output_ports=[PortConfig(id="out", port_type="default", direction="output")],
        )
    ]
    routes: list[RouteConfig] = []
    prev_node_id = "src-auto"
    prev_port_id = "out"

    for idx, st_cfg in enumerate(stations_cfg):
        st_node = NodeConfig(
            id=st_cfg.id,
            kind="station",
            operations=st_cfg.operations,
            output_capacity=st_cfg.output_capacity,
            input_ports=[PortConfig(id="in", port_type="default", direction="input")],
            output_ports=[PortConfig(id="out", port_type="default", direction="output")],
        )
        nodes.append(st_node)
        routes.append(
            RouteConfig(
                id=f"r-{prev_node_id}-{st_cfg.id}",
                source_node_id=prev_node_id,
                source_port_id=prev_port_id,
                target_node_id=st_cfg.id,
                target_port_id="in",
            )
        )
        prev_node_id = st_cfg.id
        prev_port_id = "out"

    sink_node = NodeConfig(
        id="snk-auto",
        kind="sink",
        input_ports=[PortConfig(id="in", port_type="default", direction="input")],
    )
    nodes.append(sink_node)
    routes.append(
        RouteConfig(
            id=f"r-{prev_node_id}-snk-auto",
            source_node_id=prev_node_id,
            source_port_id=prev_port_id,
            target_node_id="snk-auto",
            target_port_id="in",
        )
    )

    return MaterialFlowConfig(nodes=nodes, routes=routes)


from industrialsim.checkpoint import (
    BufferSnapshot,
    Checkpoint,
    CheckpointEventRecord,
    CheckpointInspection,
    DomainStateSnapshot,
    IncompatibleCheckpointError,
    InvalidCheckpointError,
    MachineSnapshot,
    ProductionUnitSnapshot,
    StationSnapshot,
    WorkerSnapshot,
    compute_config_hash,
    compute_model_hash,
    deserialize_checkpoint,
    inspect_checkpoint,
    load_checkpoint,
    save_checkpoint,
    serialize_checkpoint,
)


def _index_routes(routes: Sequence[RouteConfig]) -> tuple[dict[str, list[RouteConfig]], dict[str, list[RouteConfig]]]:
    routes_from: dict[str, list[RouteConfig]] = {}
    routes_to: dict[str, list[RouteConfig]] = {}
    for r in routes:
        routes_from.setdefault(r.source_node_id, []).append(r)
        routes_to.setdefault(r.target_node_id, []).append(r)
    return routes_from, routes_to


@dataclass
class MaterialFlowTopology:
    nodes_by_id: dict[str, NodeConfig]
    sources: dict[str, NodeConfig]
    sinks: dict[str, NodeConfig]
    routes_from: dict[str, list[RouteConfig]]
    routes_to: dict[str, list[RouteConfig]]

    @classmethod
    def from_material_flow(cls, mf: MaterialFlowConfig) -> MaterialFlowTopology:
        nodes_by_id = {n.id: n for n in mf.nodes}
        sources = {n.id: n for n in mf.nodes if n.kind == "source"}
        sinks = {n.id: n for n in mf.nodes if n.kind == "sink"}
        routes_from, routes_to = _index_routes(mf.routes)
        return cls(
            nodes_by_id=nodes_by_id,
            sources=sources,
            sinks=sinks,
            routes_from=routes_from,
            routes_to=routes_to,
        )


@dataclass
class SimulationDomainState:
    units: dict[str, ProductionUnit]
    stations: dict[str, Station]
    buffers: dict[str, Buffer]
    in_flight_to: dict[str, int]
    source_pending_units: dict[str, list[str]]
    machines: dict[str, Machine] = field(default_factory=dict)
    workers: dict[str, Worker] = field(default_factory=dict)
    resource_waiters: list[dict[str, Any]] = field(default_factory=list)
    active_operations: dict[str, dict[str, Any]] = field(default_factory=dict)


def _verify_checkpoint_compatibility(
    checkpoint: Checkpoint,
    cfg: SimulationConfig,
    source_label: str,
) -> None:
    model_hash = compute_model_hash(cfg)
    if model_hash != checkpoint.model_hash:
        raise IncompatibleCheckpointError(
            f"Model hash mismatch: checkpoint requires '{checkpoint.model_hash}', but {source_label} model has '{model_hash}'"
        )
    config_hash = compute_config_hash(cfg)
    if config_hash != checkpoint.config_hash:
        raise IncompatibleCheckpointError(
            f"Configuration hash mismatch: checkpoint requires '{checkpoint.config_hash}', but {source_label} config has '{config_hash}'"
        )


class EpisodeEngine:
    def __init__(
        self,
        config: SimulationConfig,
        kernel: EventKernel,
        topology: MaterialFlowTopology,
        domain: SimulationDomainState,
        random_occurrence_counters: dict[str, int] | None = None,
        plugin_metadata: dict[str, str] | None = None,
    ) -> None:
        self.cfg = config
        self.kernel = kernel
        self.topology = topology
        self.domain = domain
        self.random_occurrence_counters = random_occurrence_counters or {}
        self.plugin_metadata = plugin_metadata or {}

        self._setup_handlers()

    @property
    def units(self) -> dict[str, ProductionUnit]:
        return self.domain.units

    @property
    def stations(self) -> dict[str, Station]:
        return self.domain.stations

    @property
    def buffers(self) -> dict[str, Buffer]:
        return self.domain.buffers

    @property
    def in_flight_to(self) -> dict[str, int]:
        return self.domain.in_flight_to

    @property
    def source_pending_units(self) -> dict[str, list[str]]:
        return self.domain.source_pending_units

    @property
    def nodes_by_id(self) -> dict[str, NodeConfig]:
        return self.topology.nodes_by_id

    @property
    def sources(self) -> dict[str, NodeConfig]:
        return self.topology.sources

    @property
    def sinks(self) -> dict[str, NodeConfig]:
        return self.topology.sinks

    @property
    def routes_from(self) -> dict[str, list[RouteConfig]]:
        return self.topology.routes_from

    @property
    def routes_to(self) -> dict[str, list[RouteConfig]]:
        return self.topology.routes_to

    @property
    def machines(self) -> dict[str, Machine]:
        return self.domain.machines

    @property
    def workers(self) -> dict[str, Worker]:
        return self.domain.workers

    @property
    def resource_waiters(self) -> list[dict[str, Any]]:
        return self.domain.resource_waiters

    @property
    def active_operations(self) -> dict[str, dict[str, Any]]:
        return self.domain.active_operations

    def _setup_handlers(self) -> None:
        self.kernel.register_handler("RELEASE_UNIT", self._handle_release)
        self.kernel.register_handler("ARRIVAL_AT_NODE", self._handle_arrival_at_node)
        self.kernel.register_handler("COMPLETE_OPERATION", self._handle_complete_operation)
        self.kernel.register_handler("SHIFT_START", self._handle_shift_start)
        self.kernel.register_handler("SHIFT_END", self._handle_shift_end)
        self.kernel.register_handler("BREAK_START", self._handle_break_start)
        self.kernel.register_handler("BREAK_END", self._handle_break_end)

    def _can_accept(self, node_id: str) -> bool:
        kind = self.nodes_by_id[node_id].kind
        if kind == "sink":
            return True
        elif kind == "buffer":
            return self.buffers[node_id].can_accept(reserved=self.in_flight_to[node_id])
        elif kind == "station":
            return self.stations[node_id].can_accept(reserved=self.in_flight_to[node_id])
        return False

    def _get_available_route(self, from_node_id: str) -> RouteConfig | None:
        routes = self.routes_from.get(from_node_id, [])
        for r in routes:
            if self._can_accept(r.target_node_id):
                return r
        return routes[0] if routes else None

    def _dispatch_unit_to_target(self, k: EventKernel, unit_id: str, route: RouteConfig) -> None:
        target_id = route.target_node_id
        self.in_flight_to[target_id] += 1
        self.units[unit_id].record_transition(
            time_ns=k.current_time_ns,
            state=ProductionUnitState.IN_TRANSPORT,
            location=route.id,
        )
        k.schedule(
            time_ns=k.current_time_ns + route.transit_time_ns,
            priority=EventPriority.COMPLETION,
            event_type="ARRIVAL_AT_NODE",
            payload={"unit_id": unit_id, "node_id": target_id},
        )

    def _pull_from_station(self, k: EventKernel, upstream_id: str, route: RouteConfig, visited: set[str]) -> bool:
        st = self.stations[upstream_id]
        if st.has_output_units() and self._can_accept(route.target_node_id):
            out_uid = st.pop_output_unit()
            assert out_uid is not None
            self._dispatch_unit_to_target(k, out_uid, route)
            if st.is_blocked:
                blocked_uid = st.blocked_unit_id
                assert blocked_uid is not None
                st.end_blocking(k.current_time_ns)
                st.enqueue_output_unit(blocked_uid)
                self.units[blocked_uid].record_transition(
                    time_ns=k.current_time_ns,
                    state=ProductionUnitState.IN_STATION,
                    location=upstream_id,
                    station_id=upstream_id,
                )
                self._try_pull_upstream(k, upstream_id, visited)
            return True
        elif st.is_blocked and self._can_accept(route.target_node_id):
            blocked_uid = st.blocked_unit_id
            assert blocked_uid is not None
            st.end_blocking(k.current_time_ns)
            self._dispatch_unit_to_target(k, blocked_uid, route)
            self._try_pull_upstream(k, upstream_id, visited)
            return True
        return False

    def _pull_from_buffer(self, k: EventKernel, upstream_id: str, route: RouteConfig, visited: set[str]) -> bool:
        buf = self.buffers[upstream_id]
        pulled = False
        while buf.has_occupants() and self._can_accept(route.target_node_id):
            out_uid = buf.pop_unit()
            assert out_uid is not None
            self._dispatch_unit_to_target(k, out_uid, route)
            pulled = True
        if pulled:
            self._try_pull_upstream(k, upstream_id, visited)
        return pulled

    def _pull_from_source(self, k: EventKernel, upstream_id: str, route: RouteConfig, visited: set[str]) -> bool:
        pulled = False
        while self.source_pending_units[upstream_id] and self._can_accept(route.target_node_id):
            out_uid = self.source_pending_units[upstream_id].pop(0)
            self._dispatch_unit_to_target(k, out_uid, route)
            pulled = True
        return pulled

    def _try_pull_upstream(self, k: EventKernel, node_id: str, visited: set[str] | None = None) -> None:
        if visited is None:
            visited = set()
        if node_id in visited:
            return
        visited.add(node_id)

        for route in self.routes_to.get(node_id, []):
            upstream_id = route.source_node_id
            kind = self.nodes_by_id[upstream_id].kind
            if kind == "station":
                self._pull_from_station(k, upstream_id, route, visited)
            elif kind == "buffer":
                self._pull_from_buffer(k, upstream_id, route, visited)
            elif kind == "source":
                self._pull_from_source(k, upstream_id, route, visited)

    def _handle_release(self, k: EventKernel, event: ScheduledEvent) -> None:
        unit_id = event.payload["unit_id"]
        source_id = event.payload["source_id"]
        unit = self.units[unit_id]
        unit.record_transition(
            time_ns=k.current_time_ns,
            state=ProductionUnitState.RELEASED,
            location=source_id,
        )

        route = self._get_available_route(source_id)
        if route and self._can_accept(route.target_node_id):
            self._dispatch_unit_to_target(k, unit_id, route)
        else:
            self.source_pending_units[source_id].append(unit_id)

    def _handle_sink_arrival(self, k: EventKernel, unit_id: str, node_id: str) -> None:
        self.units[unit_id].record_transition(
            time_ns=k.current_time_ns,
            state=ProductionUnitState.TERMINAL,
            location="terminal",
        )
        self._try_pull_upstream(k, node_id)

    def _handle_buffer_arrival(self, k: EventKernel, unit_id: str, node_id: str) -> None:
        buf = self.buffers[node_id]
        buf.add_unit(unit_id)
        self.units[unit_id].record_transition(
            time_ns=k.current_time_ns,
            state=ProductionUnitState.IN_BUFFER,
            location=node_id,
        )
        route = self._get_available_route(node_id)
        if route and self._can_accept(route.target_node_id):
            oldest_uid = buf.pop_unit()
            assert oldest_uid is not None
            self._dispatch_unit_to_target(k, oldest_uid, route)
        self._try_pull_upstream(k, node_id)

    def _can_acquire_resources(
        self, op: Operation, station_id: str, time_ns: int
    ) -> tuple[bool, list[str], list[dict[str, Any]]]:
        allocated_machines: list[str] = []
        for m_id in op.required_machines:
            mach = self.machines.get(m_id)
            if not mach or not mach.can_allocate(1, time_ns):
                return False, [], []
            allocated_machines.append(m_id)

        allocated_workers: list[dict[str, Any]] = []
        temp_worker_allocations: dict[str, int] = {}

        for req in op.required_workers:
            needed_count = req.get("count", 1)
            target_worker_id = req.get("worker_id")
            target_qual = req.get("qualification")

            if target_worker_id is not None:
                w = self.workers.get(target_worker_id)
                if not w or not w.is_available(time_ns):
                    return False, [], []
                curr_allocated = temp_worker_allocations.get(w.id, 0)
                if w.available_capacity(time_ns) - curr_allocated < needed_count:
                    return False, [], []
                temp_worker_allocations[w.id] = curr_allocated + needed_count
                allocated_workers.append({"worker_id": w.id, "count": needed_count, "qualification": target_qual})
            elif target_qual is not None:
                candidates = [
                    w for w in self.workers.values()
                    if target_qual in w.qualifications and w.is_available(time_ns)
                ]
                candidates.sort(key=lambda w: (0 if w.kind == "pool" else 1, w.id))

                satisfied = 0
                for c in candidates:
                    curr_allocated = temp_worker_allocations.get(c.id, 0)
                    avail = c.available_capacity(time_ns) - curr_allocated
                    if avail > 0:
                        take = min(avail, needed_count - satisfied)
                        temp_worker_allocations[c.id] = curr_allocated + take
                        allocated_workers.append({"worker_id": c.id, "count": take, "qualification": target_qual})
                        satisfied += take
                        if satisfied == needed_count:
                            break
                if satisfied < needed_count:
                    return False, [], []

        return True, allocated_machines, allocated_workers

    def _acquire_resources(
        self,
        station_id: str,
        unit_id: str,
        op: Operation,
        op_index: int,
        remaining_duration_ns: int,
        mach_ids: list[str],
        worker_allocs: list[dict[str, Any]],
        time_ns: int,
    ) -> int:
        for m_id in mach_ids:
            self.machines[m_id].allocate(station_id, unit_id, op.id, time_ns)
        for alloc in worker_allocs:
            for _ in range(alloc["count"]):
                self.workers[alloc["worker_id"]].allocate(station_id, unit_id, op.id, time_ns)

        token = self.kernel.sequence_counter + 1
        self.active_operations[station_id] = {
            "station_id": station_id,
            "unit_id": unit_id,
            "op_id": op.id,
            "op_index": op_index,
            "start_time_ns": time_ns,
            "remaining_duration_ns": remaining_duration_ns,
            "machines": list(mach_ids),
            "workers": [dict(a) for a in worker_allocs],
            "token": token,
        }
        return token

    def _release_resources(self, station_id: str, time_ns: int, completed: bool = False) -> dict[str, Any] | None:
        active_op = self.active_operations.pop(station_id, None)
        if not active_op:
            return None
        unit_id = active_op["unit_id"]
        op_id = active_op["op_id"]
        for m_id in active_op["machines"]:
            if m_id in self.machines:
                self.machines[m_id].release(station_id, unit_id, op_id, time_ns, completed=completed)
        for alloc in active_op["workers"]:
            w_id = alloc["worker_id"]
            if w_id in self.workers:
                for _ in range(alloc["count"]):
                    self.workers[w_id].release(station_id, unit_id, op_id, time_ns, completed=completed)
        return active_op

    def _try_allocate_pending_resources(self, time_ns: int) -> None:
        if not self.resource_waiters:
            return

        self.resource_waiters.sort(
            key=lambda w: (
                w["waiting_since_ns"],
                w.get("priority", 0),
                w["station_id"],
                w["unit_id"],
            )
        )

        allocated_indices: list[int] = []
        for idx, waiter in enumerate(self.resource_waiters):
            station_id = waiter["station_id"]
            st = self.stations[station_id]
            unit_id = waiter["unit_id"]
            op_index = waiter["op_index"]
            ops_list = list(st.operations.values())
            op = ops_list[op_index]

            can_acq, mach_ids, worker_allocs = self._can_acquire_resources(op, station_id, time_ns)
            if can_acq:
                allocated_indices.append(idx)
                rem_dur = waiter.get("remaining_duration_ns", op.duration_ns)
                if waiter.get("is_resuming"):
                    st.record_resume()
                elif waiter.get("is_restarting"):
                    st.record_restart()
                token = self._acquire_resources(
                    station_id=station_id,
                    unit_id=unit_id,
                    op=op,
                    op_index=op_index,
                    remaining_duration_ns=rem_dur,
                    mach_ids=mach_ids,
                    worker_allocs=worker_allocs,
                    time_ns=time_ns,
                )
                st.start_operation(unit_id, op.id, time_ns)
                self.kernel.schedule(
                    time_ns=time_ns + rem_dur,
                    priority=EventPriority.COMPLETION,
                    event_type="COMPLETE_OPERATION",
                    payload={"unit_id": unit_id, "station_id": station_id, "op_index": op_index, "token": token},
                )

        if allocated_indices:
            for idx in reversed(allocated_indices):
                self.resource_waiters.pop(idx)

    def _interrupt_operation(self, station_id: str, time_ns: int) -> None:
        active_op = self.active_operations.get(station_id)
        if not active_op:
            return

        st = self.stations[station_id]
        unit_id = active_op["unit_id"]
        op = list(st.operations.values())[active_op["op_index"]]
        policy = op.interruption_policy

        # Cancel current token
        active_op["token"] = -1

        if policy == "resume":
            elapsed = time_ns - active_op["start_time_ns"]
            active_op["remaining_duration_ns"] = max(0, active_op["remaining_duration_ns"] - elapsed)
            rem_dur = active_op["remaining_duration_ns"]
            st.interrupt_operation(time_ns)
            self._release_resources(station_id, time_ns, completed=False)
            self.resource_waiters.append({
                "station_id": station_id,
                "unit_id": unit_id,
                "op_index": active_op["op_index"],
                "waiting_since_ns": time_ns,
                "remaining_duration_ns": rem_dur,
                "is_resuming": True,
            })
        elif policy == "restart":
            st.interrupt_operation(time_ns)
            self._release_resources(station_id, time_ns, completed=False)
            self.resource_waiters.append({
                "station_id": station_id,
                "unit_id": unit_id,
                "op_index": active_op["op_index"],
                "waiting_since_ns": time_ns,
                "remaining_duration_ns": op.duration_ns,
                "is_restarting": True,
            })
        elif policy == "scrap":
            st.scrap_operation(time_ns)
            u = self.units[unit_id]
            u.quality_state = "scrapped"
            u.record_transition(time_ns, ProductionUnitState.TERMINAL, location="terminal")
            self._release_resources(station_id, time_ns, completed=False)
            self._try_pull_upstream(self.kernel, station_id)

    def _handle_shift_start(self, k: EventKernel, event: ScheduledEvent) -> None:
        worker_id = event.payload.get("worker_id")
        machine_id = event.payload.get("machine_id")
        if worker_id and worker_id in self.workers:
            w = self.workers[worker_id]
            w.pending_off_shift = False
            w.update_metrics(k.current_time_ns)
        if machine_id and machine_id in self.machines:
            m = self.machines[machine_id]
            m.pending_off_shift = False
            m.update_metrics(k.current_time_ns)
        self._try_allocate_pending_resources(k.current_time_ns)

    def _handle_shift_end(self, k: EventKernel, event: ScheduledEvent) -> None:
        worker_id = event.payload.get("worker_id")
        machine_id = event.payload.get("machine_id")
        handover_rule = event.payload.get("handover_rule", "handover")

        if worker_id and worker_id in self.workers:
            w = self.workers[worker_id]
            w.update_metrics(k.current_time_ns)

            active_stations = [
                s_id for s_id, a_op in list(self.active_operations.items())
                if any(alloc["worker_id"] == worker_id for alloc in a_op["workers"])
            ]

            for s_id in active_stations:
                if handover_rule == "run_off":
                    w.pending_off_shift = True
                elif handover_rule == "handover":
                    active_op = self.active_operations[s_id]
                    op = list(self.stations[s_id].operations.values())[active_op["op_index"]]

                    allocs_to_replace = [
                        alloc for alloc in active_op["workers"]
                        if alloc["worker_id"] == worker_id
                    ]
                    replacements: list[tuple[dict[str, Any], Worker]] = []
                    temp_reserved: dict[str, int] = {}
                    all_replaced = True

                    for alloc in allocs_to_replace:
                        req_qual = alloc.get("qualification")
                        needed = alloc["count"]
                        found_worker = None
                        for other_w in sorted(self.workers.values(), key=lambda x: x.id):
                            if other_w.id != worker_id and other_w.is_available(k.current_time_ns):
                                matches_qual = (req_qual in other_w.qualifications) if req_qual else any(q in other_w.qualifications for q in w.qualifications)
                                if matches_qual:
                                    avail = other_w.available_capacity(k.current_time_ns) - temp_reserved.get(other_w.id, 0)
                                    if avail >= needed:
                                        found_worker = other_w
                                        temp_reserved[other_w.id] = temp_reserved.get(other_w.id, 0) + needed
                                        break
                        if found_worker is not None:
                            replacements.append((alloc, found_worker))
                        else:
                            all_replaced = False
                            break

                    if all_replaced:
                        for alloc, incoming_worker in replacements:
                            for _ in range(alloc["count"]):
                                w.release(s_id, active_op["unit_id"], op.id, k.current_time_ns, completed=False)
                                incoming_worker.allocate(s_id, active_op["unit_id"], op.id, k.current_time_ns)
                            alloc["worker_id"] = incoming_worker.id
                    else:
                        self._interrupt_operation(s_id, k.current_time_ns)
                else:  # interrupt
                    self._interrupt_operation(s_id, k.current_time_ns)

        if machine_id and machine_id in self.machines:
            mach = self.machines[machine_id]
            mach.update_metrics(k.current_time_ns)
            active_stations = [
                s_id for s_id, a_op in list(self.active_operations.items())
                if machine_id in a_op["machines"]
            ]
            for s_id in active_stations:
                if handover_rule == "run_off":
                    mach.pending_off_shift = True
                else:
                    self._interrupt_operation(s_id, k.current_time_ns)

        self._try_allocate_pending_resources(k.current_time_ns)

    def _handle_break_start(self, k: EventKernel, event: ScheduledEvent) -> None:
        worker_id = event.payload.get("worker_id")
        machine_id = event.payload.get("machine_id")

        if worker_id and worker_id in self.workers:
            self.workers[worker_id].update_metrics(k.current_time_ns)
            active_stations = [
                s_id for s_id, a_op in list(self.active_operations.items())
                if any(alloc["worker_id"] == worker_id for alloc in a_op["workers"])
            ]
            for s_id in active_stations:
                self._interrupt_operation(s_id, k.current_time_ns)

        if machine_id and machine_id in self.machines:
            self.machines[machine_id].update_metrics(k.current_time_ns)
            active_stations = [
                s_id for s_id, a_op in list(self.active_operations.items())
                if machine_id in a_op["machines"]
            ]
            for s_id in active_stations:
                self._interrupt_operation(s_id, k.current_time_ns)

    def _handle_break_end(self, k: EventKernel, event: ScheduledEvent) -> None:
        worker_id = event.payload.get("worker_id")
        machine_id = event.payload.get("machine_id")
        if worker_id and worker_id in self.workers:
            self.workers[worker_id].update_metrics(k.current_time_ns)
        if machine_id and machine_id in self.machines:
            self.machines[machine_id].update_metrics(k.current_time_ns)
        self._try_allocate_pending_resources(k.current_time_ns)

    def _handle_station_arrival(self, k: EventKernel, unit_id: str, node_id: str) -> None:
        st = self.stations[node_id]
        assert st.can_accept(), f"Station {node_id} accepted unit {unit_id} while busy/blocked"
        st.current_unit_id = unit_id
        op = list(st.operations.values())[0]
        self.units[unit_id].record_transition(
            time_ns=k.current_time_ns,
            state=ProductionUnitState.IN_STATION,
            location=node_id,
            station_id=node_id,
            operation_id=op.id,
        )

        can_acq, mach_ids, worker_allocs = self._can_acquire_resources(op, node_id, k.current_time_ns)
        if can_acq:
            token = self._acquire_resources(
                station_id=node_id,
                unit_id=unit_id,
                op=op,
                op_index=0,
                remaining_duration_ns=op.duration_ns,
                mach_ids=mach_ids,
                worker_allocs=worker_allocs,
                time_ns=k.current_time_ns,
            )
            st.start_operation(unit_id, op.id, k.current_time_ns)
            k.schedule(
                time_ns=k.current_time_ns + op.duration_ns,
                priority=EventPriority.COMPLETION,
                event_type="COMPLETE_OPERATION",
                payload={"unit_id": unit_id, "station_id": node_id, "op_index": 0, "token": token},
            )
        else:
            st.start_waiting(k.current_time_ns)
            self.resource_waiters.append({
                "station_id": node_id,
                "unit_id": unit_id,
                "op_index": 0,
                "waiting_since_ns": k.current_time_ns,
                "remaining_duration_ns": op.duration_ns,
            })

    def _handle_arrival_at_node(self, k: EventKernel, event: ScheduledEvent) -> None:
        unit_id = event.payload["unit_id"]
        node_id = event.payload["node_id"]
        self.in_flight_to[node_id] -= 1
        kind = self.nodes_by_id[node_id].kind
        if kind == "sink":
            self._handle_sink_arrival(k, unit_id, node_id)
        elif kind == "buffer":
            self._handle_buffer_arrival(k, unit_id, node_id)
        elif kind == "station":
            self._handle_station_arrival(k, unit_id, node_id)

    def _handle_complete_operation(self, k: EventKernel, event: ScheduledEvent) -> None:
        unit_id = event.payload["unit_id"]
        station_id = event.payload["station_id"]
        op_index = event.payload.get("op_index", 0)
        expected_token = event.payload.get("token")

        active_op = self.active_operations.get(station_id)
        if expected_token is not None:
            if not active_op or active_op.get("token") != expected_token:
                return

        st = self.stations[station_id]
        ops_list = list(st.operations.values())
        current_op = ops_list[op_index]

        self._release_resources(station_id, k.current_time_ns, completed=True)
        st.complete_operation(current_op.id, k.current_time_ns)

        # If station has multiple operations and more remain for this unit:
        if op_index + 1 < len(ops_list):
            st.current_unit_id = unit_id
            next_op = ops_list[op_index + 1]
            self.units[unit_id].record_transition(
                time_ns=k.current_time_ns,
                state=ProductionUnitState.IN_STATION,
                location=station_id,
                station_id=station_id,
                operation_id=next_op.id,
            )
            can_acq, mach_ids, worker_allocs = self._can_acquire_resources(next_op, station_id, k.current_time_ns)
            if can_acq:
                token = self._acquire_resources(
                    station_id=station_id,
                    unit_id=unit_id,
                    op=next_op,
                    op_index=op_index + 1,
                    remaining_duration_ns=next_op.duration_ns,
                    mach_ids=mach_ids,
                    worker_allocs=worker_allocs,
                    time_ns=k.current_time_ns,
                )
                st.start_operation(unit_id, next_op.id, k.current_time_ns)
                k.schedule(
                    time_ns=k.current_time_ns + next_op.duration_ns,
                    priority=EventPriority.COMPLETION,
                    event_type="COMPLETE_OPERATION",
                    payload={"unit_id": unit_id, "station_id": station_id, "op_index": op_index + 1, "token": token},
                )
            else:
                st.start_waiting(k.current_time_ns)
                self.resource_waiters.append({
                    "station_id": station_id,
                    "unit_id": unit_id,
                    "op_index": op_index + 1,
                    "waiting_since_ns": k.current_time_ns,
                    "remaining_duration_ns": next_op.duration_ns,
                })
            self._try_allocate_pending_resources(k.current_time_ns)
            return

        # Last operation completed for this unit:
        route = self._get_available_route(station_id)
        downstream_can_accept = route is not None and self._can_accept(route.target_node_id)

        if downstream_can_accept and route is not None:
            st.current_unit_id = None
            self._dispatch_unit_to_target(k, unit_id, route)
            self._try_pull_upstream(k, station_id)
        else:
            if st.has_output_space():
                st.current_unit_id = None
                st.enqueue_output_unit(unit_id)
                self.units[unit_id].record_transition(
                    time_ns=k.current_time_ns,
                    state=ProductionUnitState.IN_STATION,
                    location=station_id,
                    station_id=station_id,
                )
                self._try_pull_upstream(k, station_id)
            else:
                st.start_blocking(unit_id, k.current_time_ns)
                self.units[unit_id].record_transition(
                    time_ns=k.current_time_ns,
                    state=ProductionUnitState.BLOCKED,
                    location=station_id,
                    station_id=station_id,
                )

        self._try_allocate_pending_resources(k.current_time_ns)

    def _is_terminal_condition_met(self, k: EventKernel) -> bool:
        if self.cfg.episode.end_condition.type == "all_units_terminal":
            return all(u.state == ProductionUnitState.TERMINAL for u in self.units.values())
        return False

    @classmethod
    def create(cls, cfg: SimulationConfig) -> EpisodeEngine:
        units: dict[str, ProductionUnit] = {
            u_cfg.id: ProductionUnit(id=u_cfg.id, variant=u_cfg.variant)
            for u_cfg in cfg.production_units
        }

        kernel = EventKernel(initial_time_ns=cfg.episode.start_time_ns)

        mf: MaterialFlowConfig = (
            cfg.material_flow
            if cfg.material_flow is not None
            else _synthesize_minimal_material_flow(cfg.stations)
        )

        nodes_by_id = {n.id: n for n in mf.nodes}
        stations: dict[str, Station] = {}
        buffers: dict[str, Buffer] = {}
        sources: dict[str, NodeConfig] = {}
        sinks: dict[str, NodeConfig] = {}

        for n in mf.nodes:
            if n.kind == "station":
                stations[n.id] = Station(
                    id=n.id,
                    operations={
                        op.id: Operation(
                            id=op.id,
                            duration_ns=op.duration_ns,
                            required_machines=list(op.required_machines),
                            required_workers=[req.model_dump() for req in op.required_workers],
                            interruption_policy=op.interruption_policy,
                        )
                        for op in n.operations
                    },
                    output_capacity=n.output_capacity,
                )
            elif n.kind == "buffer":
                assert n.capacity is not None
                buffers[n.id] = Buffer(id=n.id, capacity=n.capacity)
            elif n.kind == "source":
                sources[n.id] = n
            elif n.kind == "sink":
                sinks[n.id] = n

        routes_from, routes_to = _index_routes(mf.routes)

        in_flight_to: dict[str, int] = {node.id: 0 for node in mf.nodes}
        source_pending_units: dict[str, list[str]] = {nid: [] for nid in sources}

        sole_source_id = next(iter(sources.keys())) if len(sources) == 1 else None

        for u_cfg in cfg.production_units:
            release_ns = max(cfg.episode.start_time_ns, u_cfg.release_time_ns)
            source_id = u_cfg.source_id or sole_source_id
            if source_id is None or source_id not in sources:
                raise ValueError(
                    f"Production unit '{u_cfg.id}' cannot be released: no valid source node found in material flow"
                )
            kernel.schedule(
                time_ns=release_ns,
                priority=EventPriority.NEW_WORK,
                event_type="RELEASE_UNIT",
                payload={"unit_id": u_cfg.id, "source_id": source_id},
            )

        machines: dict[str, Machine] = {}
        for m_cfg in cfg.machines:
            machines[m_cfg.id] = Machine(
                id=m_cfg.id,
                capacity=m_cfg.capacity,
                shifts=[
                    Shift(
                        id=s.id,
                        start_time_ns=s.start_time_ns,
                        end_time_ns=s.end_time_ns,
                        handover_rule=s.handover_rule,
                        breaks=[Break(b.start_time_ns, b.end_time_ns, b.duration_ns) for b in s.breaks],
                    )
                    for s in m_cfg.shifts
                ],
                breaks=[
                    Break(b.start_time_ns, b.end_time_ns, b.duration_ns)
                    for b in m_cfg.breaks
                ],
            )
            for s in m_cfg.shifts:
                if s.start_time_ns >= cfg.episode.start_time_ns:
                    kernel.schedule(
                        time_ns=s.start_time_ns,
                        priority=EventPriority.RESOURCE,
                        event_type="SHIFT_START",
                        payload={"machine_id": m_cfg.id, "shift_id": s.id},
                    )
                if s.end_time_ns >= cfg.episode.start_time_ns:
                    kernel.schedule(
                        time_ns=s.end_time_ns,
                        priority=EventPriority.RESOURCE,
                        event_type="SHIFT_END",
                        payload={"machine_id": m_cfg.id, "shift_id": s.id, "handover_rule": s.handover_rule},
                    )
                for b in s.breaks:
                    if b.start_time_ns >= cfg.episode.start_time_ns:
                        kernel.schedule(
                            time_ns=b.start_time_ns,
                            priority=EventPriority.RESOURCE,
                            event_type="BREAK_START",
                            payload={"machine_id": m_cfg.id},
                        )
                    if b.end_time_ns >= cfg.episode.start_time_ns:
                        kernel.schedule(
                            time_ns=b.end_time_ns,
                            priority=EventPriority.RESOURCE,
                            event_type="BREAK_END",
                            payload={"machine_id": m_cfg.id},
                        )
            for b in m_cfg.breaks:
                if b.start_time_ns >= cfg.episode.start_time_ns:
                    kernel.schedule(
                        time_ns=b.start_time_ns,
                        priority=EventPriority.RESOURCE,
                        event_type="BREAK_START",
                        payload={"machine_id": m_cfg.id},
                    )
                if b.end_time_ns >= cfg.episode.start_time_ns:
                    kernel.schedule(
                        time_ns=b.end_time_ns,
                        priority=EventPriority.RESOURCE,
                        event_type="BREAK_END",
                        payload={"machine_id": m_cfg.id},
                    )

        workers: dict[str, Worker] = {}
        for w_cfg in cfg.workers:
            workers[w_cfg.id] = Worker(
                id=w_cfg.id,
                kind=w_cfg.kind,
                capacity=w_cfg.capacity,
                qualifications=list(w_cfg.qualifications),
                shifts=[
                    Shift(
                        id=s.id,
                        start_time_ns=s.start_time_ns,
                        end_time_ns=s.end_time_ns,
                        handover_rule=s.handover_rule,
                        breaks=[Break(b.start_time_ns, b.end_time_ns, b.duration_ns) for b in s.breaks],
                    )
                    for s in w_cfg.shifts
                ],
                breaks=[
                    Break(b.start_time_ns, b.end_time_ns, b.duration_ns)
                    for b in w_cfg.breaks
                ],
            )
            for s in w_cfg.shifts:
                if s.start_time_ns >= cfg.episode.start_time_ns:
                    kernel.schedule(
                        time_ns=s.start_time_ns,
                        priority=EventPriority.RESOURCE,
                        event_type="SHIFT_START",
                        payload={"worker_id": w_cfg.id, "shift_id": s.id},
                    )
                if s.end_time_ns >= cfg.episode.start_time_ns:
                    kernel.schedule(
                        time_ns=s.end_time_ns,
                        priority=EventPriority.RESOURCE,
                        event_type="SHIFT_END",
                        payload={"worker_id": w_cfg.id, "shift_id": s.id, "handover_rule": s.handover_rule},
                    )
                for b in s.breaks:
                    if b.start_time_ns >= cfg.episode.start_time_ns:
                        kernel.schedule(
                            time_ns=b.start_time_ns,
                            priority=EventPriority.RESOURCE,
                            event_type="BREAK_START",
                            payload={"worker_id": w_cfg.id},
                        )
                    if b.end_time_ns >= cfg.episode.start_time_ns:
                        kernel.schedule(
                            time_ns=b.end_time_ns,
                            priority=EventPriority.RESOURCE,
                            event_type="BREAK_END",
                            payload={"worker_id": w_cfg.id},
                        )
            for b in w_cfg.breaks:
                if b.start_time_ns >= cfg.episode.start_time_ns:
                    kernel.schedule(
                        time_ns=b.start_time_ns,
                        priority=EventPriority.RESOURCE,
                        event_type="BREAK_START",
                        payload={"worker_id": w_cfg.id},
                    )
                if b.end_time_ns >= cfg.episode.start_time_ns:
                    kernel.schedule(
                        time_ns=b.end_time_ns,
                        priority=EventPriority.RESOURCE,
                        event_type="BREAK_END",
                        payload={"worker_id": w_cfg.id},
                    )

        topology = MaterialFlowTopology.from_material_flow(mf)
        domain = SimulationDomainState(
            units=units,
            stations=stations,
            buffers=buffers,
            in_flight_to=in_flight_to,
            source_pending_units=source_pending_units,
            machines=machines,
            workers=workers,
        )

        return cls(
            config=cfg,
            kernel=kernel,
            topology=topology,
            domain=domain,
        )

    @classmethod
    def restore(
        cls,
        checkpoint: Checkpoint,
        config: SimulationConfig | None = None,
    ) -> EpisodeEngine:
        # Schema and kernel version compatibility checks
        if checkpoint.schema_version != "1.0":
            raise IncompatibleCheckpointError(
                f"Incompatible schema version: expected '1.0', got '{checkpoint.schema_version}'"
            )
        if checkpoint.kernel_version != "1.0":
            raise IncompatibleCheckpointError(
                f"Incompatible kernel version: expected '1.0', got '{checkpoint.kernel_version}'"
            )
        if checkpoint.plugin_metadata:
            raise IncompatibleCheckpointError(
                f"Incompatible plugin metadata: plugins {list(checkpoint.plugin_metadata.keys())} are not available"
            )

        # Resolve and validate configuration: prioritize model hash diagnostic over config hash
        if config is not None:
            cfg = config
            _verify_checkpoint_compatibility(checkpoint, cfg, source_label="provided")
        else:
            if not checkpoint.configuration:
                raise IncompatibleCheckpointError(
                    "Checkpoint contains no embedded configuration, and no configuration was provided"
                )
            cfg = SimulationConfig.model_validate(checkpoint.configuration)
            _verify_checkpoint_compatibility(checkpoint, cfg, source_label="embedded")

        mf: MaterialFlowConfig = (
            cfg.material_flow
            if cfg.material_flow is not None
            else _synthesize_minimal_material_flow(cfg.stations)
        )

        nodes_by_id = {n.id: n for n in mf.nodes}
        sources = {n.id: n for n in mf.nodes if n.kind == "source"}
        sinks = {n.id: n for n in mf.nodes if n.kind == "sink"}

        routes_from, routes_to = _index_routes(mf.routes)

        # Restore kernel
        kernel = EventKernel(initial_time_ns=checkpoint.simulated_time_ns)
        kernel.restore(
            {
                "current_time_ns": checkpoint.simulated_time_ns,
                "sequence_counter": checkpoint.next_sequence - 1,
                "events_processed": checkpoint.events_processed,
                "queue": checkpoint.event_queue,
            }
        )

        # Restore production units via domain encapsulation
        domain_state = checkpoint.domain_state
        units: dict[str, ProductionUnit] = {
            uid: ProductionUnit.from_snapshot(u_data)
            for uid, u_data in domain_state["production_units"].items()
        }

        # Restore stations via domain encapsulation
        stations: dict[str, Station] = {}
        for st_id, st_data in domain_state["stations"].items():
            node = nodes_by_id[st_id]
            st = Station(
                id=st_id,
                operations={
                    op.id: Operation(
                        id=op.id,
                        duration_ns=op.duration_ns,
                        required_machines=list(op.required_machines),
                        required_workers=[req.model_dump() for req in op.required_workers],
                        interruption_policy=op.interruption_policy,
                    )
                    for op in node.operations
                },
                output_capacity=node.output_capacity,
            )
            st.restore_state(st_data)
            stations[st_id] = st

        # Restore buffers via domain encapsulation
        buffers: dict[str, Buffer] = {}
        for buf_id, buf_data in domain_state.get("buffers", {}).items():
            buf = Buffer(id=buf_id, capacity=buf_data["capacity"])
            buf.restore_state(buf_data)
            buffers[buf_id] = buf

        # Restore machines
        machines: dict[str, Machine] = {}
        for m_cfg in cfg.machines:
            mach = Machine(
                id=m_cfg.id,
                capacity=m_cfg.capacity,
                shifts=[
                    Shift(
                        id=s.id,
                        start_time_ns=s.start_time_ns,
                        end_time_ns=s.end_time_ns,
                        handover_rule=s.handover_rule,
                        breaks=[Break(b.start_time_ns, b.end_time_ns, b.duration_ns) for b in s.breaks],
                    )
                    for s in m_cfg.shifts
                ],
                breaks=[
                    Break(b.start_time_ns, b.end_time_ns, b.duration_ns)
                    for b in m_cfg.breaks
                ],
            )
            if m_cfg.id in domain_state.get("machines", {}):
                mach.restore_state(domain_state["machines"][m_cfg.id])
            machines[m_cfg.id] = mach

        # Restore workers
        workers: dict[str, Worker] = {}
        for w_cfg in cfg.workers:
            worker = Worker(
                id=w_cfg.id,
                kind=w_cfg.kind,
                capacity=w_cfg.capacity,
                qualifications=list(w_cfg.qualifications),
                shifts=[
                    Shift(
                        id=s.id,
                        start_time_ns=s.start_time_ns,
                        end_time_ns=s.end_time_ns,
                        handover_rule=s.handover_rule,
                        breaks=[Break(b.start_time_ns, b.end_time_ns, b.duration_ns) for b in s.breaks],
                    )
                    for s in w_cfg.shifts
                ],
                breaks=[
                    Break(b.start_time_ns, b.end_time_ns, b.duration_ns)
                    for b in w_cfg.breaks
                ],
            )
            if w_cfg.id in domain_state.get("workers", {}):
                worker.restore_state(domain_state["workers"][w_cfg.id])
            workers[w_cfg.id] = worker

        in_flight_to = {node.id: 0 for node in mf.nodes}
        in_flight_to.update(domain_state.get("in_flight_to", {}))

        source_pending_units = {
            nid: list(domain_state.get("source_pending_units", {}).get(nid, []))
            for nid in sources
        }

        resource_waiters = list(domain_state.get("resource_waiters", []))
        active_operations = {k: dict(v) for k, v in domain_state.get("active_operations", {}).items()}

        topology = MaterialFlowTopology.from_material_flow(mf)
        domain = SimulationDomainState(
            units=units,
            stations=stations,
            buffers=buffers,
            in_flight_to=in_flight_to,
            source_pending_units=source_pending_units,
            machines=machines,
            workers=workers,
            resource_waiters=resource_waiters,
            active_operations=active_operations,
        )

        return cls(
            config=cfg,
            kernel=kernel,
            topology=topology,
            domain=domain,
            random_occurrence_counters=checkpoint.random_occurrence_counters,
            plugin_metadata=checkpoint.plugin_metadata,
        )

    def create_checkpoint(self) -> Checkpoint:
        snap = self.kernel.snapshot()
        domain_state = DomainStateSnapshot(
            production_units={
                u.id: ProductionUnitSnapshot.from_dict(u.to_snapshot())
                for u in self.units.values()
            },
            stations={
                s.id: StationSnapshot.from_dict(s.to_snapshot())
                for s in self.stations.values()
            },
            buffers={
                b.id: BufferSnapshot.from_dict(b.to_snapshot())
                for b in self.buffers.values()
            },
            machines={
                m.id: MachineSnapshot.from_dict(m.to_snapshot())
                for m in self.machines.values()
            },
            workers={
                w.id: WorkerSnapshot.from_dict(w.to_snapshot())
                for w in self.workers.values()
            },
            in_flight_to=dict(self.in_flight_to),
            source_pending_units={k: list(v) for k, v in self.source_pending_units.items()},
            resource_waiters=list(self.resource_waiters),
            active_operations={k: dict(v) for k, v in self.active_operations.items()},
        )

        return Checkpoint(
            schema_version="1.0",
            kernel_version="1.0",
            model_hash=compute_model_hash(self.cfg),
            config_hash=compute_config_hash(self.cfg),
            simulated_time_ns=self.kernel.current_time_ns,
            next_sequence=snap["sequence_counter"] + 1,
            events_processed=self.kernel.events_processed,
            event_queue=[
                CheckpointEventRecord.from_dict(e) if isinstance(e, dict) else e
                for e in snap["queue"]
            ],
            domain_state=domain_state,
            root_seed=self.cfg.seed,
            random_occurrence_counters=dict(self.random_occurrence_counters),
            plugin_metadata=dict(self.plugin_metadata),
            configuration=self.cfg.model_dump(mode="json"),
        )

    def run(self, pause_at_ns: int | None = None) -> EpisodeSummary:
        if pause_at_ns is not None:
            max_t = pause_at_ns
            if self.cfg.episode.end_condition.max_time_ns is not None:
                max_t = min(max_t, self.cfg.episode.end_condition.max_time_ns)
            self.kernel.run_until(
                max_time_ns=max_t,
                stop_condition=self._is_terminal_condition_met,
            )
            if not self._is_terminal_condition_met(self.kernel) and self.kernel.current_time_ns < pause_at_ns:
                self.kernel.advance_to(pause_at_ns)
        else:
            self.kernel.run_until(
                max_time_ns=self.cfg.episode.end_condition.max_time_ns,
                stop_condition=self._is_terminal_condition_met,
            )

        return self.to_summary()

    def to_summary(self) -> EpisodeSummary:
        all_terminal = self._is_terminal_condition_met(self.kernel)
        status = "completed" if all_terminal else "incomplete"

        # Update resource and station metrics to current time
        for mach in self.machines.values():
            mach.update_metrics(self.kernel.current_time_ns)
        for w in self.workers.values():
            w.update_metrics(self.kernel.current_time_ns)
        for s in self.stations.values():
            if s.waiting_since_ns is not None:
                s.total_waiting_time_ns += self.kernel.current_time_ns - s.waiting_since_ns
                s.waiting_since_ns = self.kernel.current_time_ns

        unit_summaries = [
            ProductionUnitSummary(
                id=u.id,
                variant=u.variant,
                quality_state=u.quality_state,
                state=str(u.state),
                location=u.location,
                history=[h.to_dict() for h in u.history],
            )
            for u in self.units.values()
        ]

        station_summaries = [
            StationSummary(
                id=s.id,
                operations_completed=s.operations_completed,
                total_busy_time_ns=s.total_busy_time_ns,
                total_blocked_time_ns=s.total_blocked_time_ns,
                total_waiting_time_ns=s.total_waiting_time_ns,
                interrupted_count=s.interrupted_count,
                resumed_count=s.resumed_count,
                restarted_count=s.restarted_count,
                scrapped_count=s.scrapped_count,
            )
            for s in self.stations.values()
        ]

        buffer_summaries = [
            BufferSummary(
                id=b.id,
                capacity=b.capacity,
                peak_occupancy=b.peak_occupancy,
            )
            for b in self.buffers.values()
        ]

        machine_summaries = [
            MachineSummary(
                id=m.id,
                capacity=m.capacity,
                operations_completed=m.operations_completed,
                total_busy_time_ns=m.total_busy_time_ns,
                total_idle_time_ns=m.total_idle_time_ns,
                total_break_time_ns=m.total_break_time_ns,
                total_off_shift_time_ns=m.total_off_shift_time_ns,
                utilization=m.utilization,
            )
            for m in self.machines.values()
        ]

        worker_summaries = [
            WorkerSummary(
                id=w.id,
                kind=w.kind,
                capacity=w.capacity,
                qualifications=list(w.qualifications),
                operations_completed=w.operations_completed,
                total_busy_time_ns=w.total_busy_time_ns,
                total_idle_time_ns=w.total_idle_time_ns,
                total_break_time_ns=w.total_break_time_ns,
                total_off_shift_time_ns=w.total_off_shift_time_ns,
                utilization=w.utilization,
            )
            for w in self.workers.values()
        ]

        result_hash = _compute_result_hash(
            status=status,
            seed=self.cfg.seed,
            simulated_time_ns=self.kernel.current_time_ns,
            events_processed=self.kernel.events_processed,
            units=unit_summaries,
            stations=station_summaries,
            buffers=buffer_summaries,
            machines=machine_summaries,
            workers=worker_summaries,
        )

        return EpisodeSummary(
            status=status,
            seed=self.cfg.seed,
            simulated_time_ns=self.kernel.current_time_ns,
            events_processed=self.kernel.events_processed,
            production_units=unit_summaries,
            stations=station_summaries,
            buffers=buffer_summaries,
            machines=machine_summaries,
            workers=worker_summaries,
            result_hash=result_hash,
        )


def create_checkpoint(
    source: str | Path | dict[str, Any] | SimulationConfig | EpisodeEngine,
    at_time_ns: int | None = None,
) -> Checkpoint:
    if isinstance(source, EpisodeEngine):
        engine = source
        if at_time_ns is not None:
            if at_time_ns < engine.kernel.current_time_ns:
                raise ValueError(
                    f"Cannot create checkpoint at {at_time_ns} ns: engine has already advanced past this time to {engine.kernel.current_time_ns} ns"
                )
            if at_time_ns > engine.kernel.current_time_ns:
                engine.run(pause_at_ns=at_time_ns)
        return engine.create_checkpoint()

    if isinstance(source, SimulationConfig):
        cfg = source
    else:
        validation = validate_config(source)
        if not validation.is_valid or validation.config is None:
            raise ValueError(f"Invalid configuration: {'; '.join(validation.errors)}")
        cfg = validation.config

    engine = EpisodeEngine.create(cfg)
    if at_time_ns is not None:
        if at_time_ns < cfg.episode.start_time_ns:
            raise ValueError(
                f"Cannot create checkpoint at {at_time_ns} ns: start time is {cfg.episode.start_time_ns} ns"
            )
        if at_time_ns > cfg.episode.start_time_ns:
            engine.run(pause_at_ns=at_time_ns)
    return engine.create_checkpoint()


def restore_checkpoint(
    checkpoint: str | Path | dict[str, Any] | Checkpoint,
    config: str | Path | dict[str, Any] | SimulationConfig | None = None,
) -> EpisodeEngine:
    if isinstance(checkpoint, (str, Path)):
        cp = load_checkpoint(checkpoint)
    elif isinstance(checkpoint, dict):
        cp = deserialize_checkpoint(checkpoint)
    elif isinstance(checkpoint, Checkpoint):
        cp = checkpoint
    else:
        raise TypeError(f"Unsupported checkpoint type: {type(checkpoint).__name__}")

    cfg: SimulationConfig | None = None
    if config is not None:
        if isinstance(config, SimulationConfig):
            cfg = config
        else:
            validation = validate_config(config)
            if not validation.is_valid or validation.config is None:
                raise ValueError(f"Invalid configuration: {'; '.join(validation.errors)}")
            cfg = validation.config

    return EpisodeEngine.restore(cp, config=cfg)


def continue_checkpoint(
    checkpoint: str | Path | dict[str, Any] | Checkpoint,
    config_source: str | Path | dict[str, Any] | SimulationConfig | None = None,
    until_time_ns: int | None = None,
) -> EpisodeSummary:
    engine = restore_checkpoint(checkpoint, config=config_source)
    return engine.run(pause_at_ns=until_time_ns)


def resume_episode(
    checkpoint: str | Path | dict[str, Any] | Checkpoint,
    config_source: str | Path | dict[str, Any] | SimulationConfig | None = None,
) -> EpisodeSummary:
    return continue_checkpoint(checkpoint, config_source=config_source)


def run_episode(source: str | Path | dict[str, Any]) -> EpisodeSummary:
    validation = validate_config(source)
    if not validation.is_valid or validation.config is None:
        raise ValueError(f"Invalid configuration: {'; '.join(validation.errors)}")

    cfg = validation.config
    engine = EpisodeEngine.create(cfg)
    return engine.run()

