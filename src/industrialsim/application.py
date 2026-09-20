from __future__ import annotations

from collections import deque
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
    ProcessPlanConfig,
    RouteConfig,
    SimulationConfig,
    StationConfig,
)
from industrialsim.dispatch import BaselineDispatchPolicy, DispatchDecision
from industrialsim.domain import (
    Break,
    Buffer,
    Machine,
    Operation,
    ProductionUnit,
    ProductionUnitState,
    QualityFinding,
    Shift,
    Station,
    TransportOrder,
    TransportOrderState,
    Vehicle,
    VehicleState,
    Worker,
)
from industrialsim.kernel import EventKernel, EventPriority, ScheduledEvent
from industrialsim.random import SemanticRandomStream


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
    due_date_ns: int | None = None
    process_step_index: int = 0
    findings: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "id": self.id,
            "variant": self.variant,
            "quality_state": self.quality_state,
            "state": self.state,
            "location": self.location,
            "history": self.history,
            "process_step_index": self.process_step_index,
            "findings": list(self.findings),
        }
        if self.due_date_ns is not None:
            result["due_date_ns"] = self.due_date_ns
        return result


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
    health: float = 1.0
    operating_mode: str = "nominal"
    total_maintenance_time_ns: int = 0
    total_failed_time_ns: int = 0
    maintenance_count: int = 0
    failure_count: int = 0

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
            "health": self.health,
            "operating_mode": self.operating_mode,
            "total_maintenance_time_ns": self.total_maintenance_time_ns,
            "total_failed_time_ns": self.total_failed_time_ns,
            "maintenance_count": self.maintenance_count,
            "failure_count": self.failure_count,
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
class VehicleSummary:
    id: str
    location: str
    transports_completed: int
    total_busy_time_ns: int
    total_idle_time_ns: int
    utilization: float
    pool_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "location": self.location,
            "transports_completed": self.transports_completed,
            "total_busy_time_ns": self.total_busy_time_ns,
            "total_idle_time_ns": self.total_idle_time_ns,
            "utilization": self.utilization,
            "pool_id": self.pool_id,
        }


@dataclass(frozen=True)
class TransportOrderSummary:
    id: str
    unit_id: str
    source_node_id: str
    target_node_id: str
    route_id: str | None
    vehicle_id: str | None
    state: str
    created_time_ns: int
    dispatched_time_ns: int | None = None
    pickup_time_ns: int | None = None
    completed_time_ns: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "unit_id": self.unit_id,
            "source_node_id": self.source_node_id,
            "target_node_id": self.target_node_id,
            "route_id": self.route_id,
            "vehicle_id": self.vehicle_id,
            "state": self.state,
            "created_time_ns": self.created_time_ns,
            "dispatched_time_ns": self.dispatched_time_ns,
            "pickup_time_ns": self.pickup_time_ns,
            "completed_time_ns": self.completed_time_ns,
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
    vehicles: list[VehicleSummary] = field(default_factory=list)
    transport_orders: list[TransportOrderSummary] = field(default_factory=list)

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
            "vehicles": [v.to_dict() for v in self.vehicles],
            "transport_orders": [t.to_dict() for t in self.transport_orders],
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
    vehicles: list[VehicleSummary] | None = None,
    transport_orders: list[TransportOrderSummary] | None = None,
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
    if vehicles:
        data["vehicles"] = [v.to_dict() for v in vehicles]
    if transport_orders:
        data["transport_orders"] = [t.to_dict() for t in transport_orders]
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
    TransportOrderSnapshot,
    VehicleSnapshot,
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
    routes: list[RouteConfig]
    routes_by_id: dict[str, RouteConfig]
    routes_from: dict[str, list[RouteConfig]]
    routes_to: dict[str, list[RouteConfig]]

    def find_shortest_path_distance(self, from_node: str, to_node: str, directed: bool = True) -> int | None:
        import heapq

        if from_node == to_node:
            return 0
        adj: dict[str, list[tuple[str, int]]] = {}
        for r in self.routes:
            adj.setdefault(r.source_node_id, []).append((r.target_node_id, r.transit_time_ns))
            if not directed:
                adj.setdefault(r.target_node_id, []).append((r.source_node_id, r.transit_time_ns))

        distances: dict[str, int] = {from_node: 0}
        pq: list[tuple[int, str]] = [(0, from_node)]

        while pq:
            d, u = heapq.heappop(pq)
            if d > distances.get(u, float("inf")):
                continue
            if u == to_node:
                return d
            for v, weight in adj.get(u, []):
                new_d = d + weight
                if new_d < distances.get(v, float("inf")):
                    distances[v] = new_d
                    heapq.heappush(pq, (new_d, v))

        return distances.get(to_node)

    def compute_distance(self, from_node: str, to_node: str) -> int | None:
        if from_node == to_node:
            return 0
        dist = self.find_shortest_path_distance(from_node, to_node, directed=True)
        if dist is not None:
            return dist
        return self.find_shortest_path_distance(from_node, to_node, directed=False)

    @classmethod
    def from_material_flow(cls, mf: MaterialFlowConfig) -> MaterialFlowTopology:
        nodes_by_id = {n.id: n for n in mf.nodes}
        sources = {n.id: n for n in mf.nodes if n.kind == "source"}
        sinks = {n.id: n for n in mf.nodes if n.kind == "sink"}
        routes = list(mf.routes)
        routes_by_id = {r.id: r for r in mf.routes}
        routes_from, routes_to = _index_routes(mf.routes)
        return cls(
            nodes_by_id=nodes_by_id,
            sources=sources,
            sinks=sinks,
            routes=routes,
            routes_by_id=routes_by_id,
            routes_from=routes_from,
            routes_to=routes_to,
        )


def _create_vehicles_from_config(cfg: SimulationConfig) -> dict[str, Vehicle]:
    pools_by_id = {p.id: p for p in cfg.vehicle_pools}
    vehicles: dict[str, Vehicle] = {}
    for v_cfg in cfg.vehicles:
        pool = pools_by_id.get(v_cfg.pool_id) if v_cfg.pool_id else None
        capabilities = list(v_cfg.capabilities)
        if pool:
            for c in pool.capabilities:
                if c not in capabilities:
                    capabilities.append(c)
        speed = (
            v_cfg.speed_multiplier
            if v_cfg.speed_multiplier is not None
            else (pool.speed_multiplier if pool else 1.0)
        )
        vehicles[v_cfg.id] = Vehicle(
            id=v_cfg.id,
            initial_location=v_cfg.initial_location,
            location=v_cfg.initial_location,
            pool_id=v_cfg.pool_id,
            capabilities=capabilities,
            speed_multiplier=speed,
        )
    return vehicles


@dataclass
class SimulationDomainState:
    units: dict[str, ProductionUnit]
    stations: dict[str, Station]
    buffers: dict[str, Buffer]
    in_flight_to: dict[str, int]
    source_pending_units: dict[str, list[str]]
    machines: dict[str, Machine] = field(default_factory=dict)
    workers: dict[str, Worker] = field(default_factory=dict)
    vehicles: dict[str, Vehicle] = field(default_factory=dict)
    transport_orders: dict[str, TransportOrder] = field(default_factory=dict)
    pending_transport_orders: list[str] = field(default_factory=list)
    active_route_occupancy: dict[str, int] = field(default_factory=dict)
    resource_waiters: list[dict[str, Any]] = field(default_factory=list)
    active_operations: dict[str, dict[str, Any]] = field(default_factory=dict)
    maintenance_waiters: list[dict[str, Any]] = field(default_factory=list)
    active_maintenances: dict[str, dict[str, Any]] = field(default_factory=dict)


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
        dispatch_policy: BaselineDispatchPolicy | None = None,
    ) -> None:
        self.cfg = config
        self.kernel = kernel
        self.topology = topology
        self.domain = domain
        self.random_occurrence_counters = random_occurrence_counters or {}
        self.plugin_metadata = plugin_metadata or {}
        self.process_plans: dict[str, ProcessPlanConfig] = {
            p.variant: p for p in self.cfg.process_plans
        }
        self.random_stream = SemanticRandomStream(
            root_seed=self.cfg.seed,
            occurrence_counters=self.random_occurrence_counters,
        )
        self.dispatch_policy = dispatch_policy or BaselineDispatchPolicy()

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
    def routes(self) -> list[RouteConfig]:
        return self.topology.routes

    @property
    def routes_by_id(self) -> dict[str, RouteConfig]:
        return self.topology.routes_by_id

    @property
    def machines(self) -> dict[str, Machine]:
        return self.domain.machines

    @property
    def workers(self) -> dict[str, Worker]:
        return self.domain.workers

    @property
    def vehicles(self) -> dict[str, Vehicle]:
        return self.domain.vehicles

    @property
    def transport_orders(self) -> dict[str, TransportOrder]:
        return self.domain.transport_orders

    @property
    def pending_transport_orders(self) -> list[str]:
        return self.domain.pending_transport_orders

    @property
    def active_route_occupancy(self) -> dict[str, int]:
        return self.domain.active_route_occupancy

    @property
    def resource_waiters(self) -> list[dict[str, Any]]:
        return self.domain.resource_waiters

    @property
    def active_operations(self) -> dict[str, dict[str, Any]]:
        return self.domain.active_operations

    @property
    def maintenance_waiters(self) -> list[dict[str, Any]]:
        return self.domain.maintenance_waiters

    @property
    def active_maintenances(self) -> dict[str, dict[str, Any]]:
        return self.domain.active_maintenances

    def _setup_handlers(self) -> None:
        self.kernel.register_handler("RELEASE_UNIT", self._handle_release)
        self.kernel.register_handler("ARRIVAL_AT_NODE", self._handle_arrival_at_node)
        self.kernel.register_handler("VEHICLE_ARRIVED_AT_PICKUP", self._handle_vehicle_arrived_at_pickup)
        self.kernel.register_handler("COMPLETE_OPERATION", self._handle_complete_operation)
        self.kernel.register_handler("SHIFT_START", self._handle_shift_start)
        self.kernel.register_handler("SHIFT_END", self._handle_shift_end)
        self.kernel.register_handler("BREAK_START", self._handle_break_start)
        self.kernel.register_handler("BREAK_END", self._handle_break_end)
        self.kernel.register_handler("DISRUPTION_START", self._handle_disruption_start)
        self.kernel.register_handler("MACHINE_FAILURE", self._handle_machine_failure)
        self.kernel.register_handler("COMPLETE_REPAIR", self._handle_complete_repair)
        self.kernel.register_handler("MAINTENANCE_TRIGGER", self._handle_maintenance_trigger)
        self.kernel.register_handler("COMPLETE_MAINTENANCE", self._handle_complete_maintenance)

    def _can_accept(self, node_id: str) -> bool:
        kind = self.nodes_by_id[node_id].kind
        if kind == "sink":
            return True
        elif kind == "buffer":
            return self.buffers[node_id].can_accept(reserved=self.in_flight_to[node_id])
        elif kind == "station":
            return self.stations[node_id].can_accept(reserved=self.in_flight_to[node_id])
        return False

    def _find_path_to_target(self, start_node_id: str, target_id: str) -> int | None:
        if start_node_id == target_id:
            return 0
        queue: deque[tuple[str, int]] = deque([(start_node_id, 0)])
        visited: set[str] = {start_node_id}
        best_dist: int | None = None
        while queue:
            curr, dist = queue.popleft()
            if curr == target_id:
                if best_dist is None or dist < best_dist:
                    best_dist = dist
                continue
            if curr != start_node_id and self.nodes_by_id[curr].kind != "buffer":
                continue
            for r in self.routes_from.get(curr, []):
                nxt = r.target_node_id
                if nxt not in visited or nxt == target_id:
                    visited.add(nxt)
                    queue.append((nxt, dist + r.transit_time_ns))
        return best_dist

    def _get_target_nodes_for_unit(self, unit: ProductionUnit) -> set[str]:
        if unit.is_in_rework:
            if unit.rework_target_station_id:
                return {unit.rework_target_station_id}
            if unit.rework_operation_id:
                matching = {s_id for s_id, s in self.stations.items() if unit.rework_operation_id in s.operations}
                if matching:
                    return matching
            restoring = {s_id for s_id, s in self.stations.items() if any(op.restores_quality for op in s.operations.values())}
            if restoring:
                return restoring
        if unit.variant in self.process_plans:
            plan = self.process_plans[unit.variant]
            if unit.process_step_index < len(plan.steps):
                return set(plan.steps[unit.process_step_index].compatible_stations)
            return set(self.sinks.keys())
        return set(self.nodes_by_id.keys())

    def _compute_node_distance(self, from_node: str, to_node: str) -> int | None:
        return self.topology.compute_distance(from_node, to_node)

    def _get_candidate_routes_for_unit(self, from_node_id: str, unit: ProductionUnit) -> list[RouteConfig]:
        routes = self.routes_from.get(from_node_id, [])
        if not routes:
            return []

        if unit.variant not in self.process_plans and not unit.is_in_rework:
            return list(routes)

        target_nodes = self._get_target_nodes_for_unit(unit)
        candidates: list[RouteConfig] = []
        for r in routes:
            for target_id in target_nodes:
                d = self._find_path_to_target(r.target_node_id, target_id)
                if d is not None:
                    candidates.append(r)
                    break
        return candidates if candidates else list(routes)

    def _create_transport_order(self, unit_id: str, source_node_id: str, time_ns: int) -> TransportOrder:
        for o in self.transport_orders.values():
            if o.unit_id == unit_id and o.state in (
                TransportOrderState.PENDING,
                TransportOrderState.DISPATCHED,
                TransportOrderState.IN_TRANSIT,
            ):
                return o

        unit = self.units[unit_id]
        candidates = self._get_candidate_routes_for_unit(source_node_id, unit)
        target_node_id = candidates[0].target_node_id if candidates else ""

        order_id = f"to-{len(self.transport_orders) + 1:06d}"
        order = TransportOrder(
            id=order_id,
            unit_id=unit_id,
            source_node_id=source_node_id,
            target_node_id=target_node_id,
            created_time_ns=time_ns,
        )
        self.transport_orders[order.id] = order
        self.pending_transport_orders.append(order.id)
        return order

    def _can_unit_depart(self, node_id: str, unit_id: str) -> bool:
        kind = self.nodes_by_id[node_id].kind
        if kind == "source":
            pending = self.source_pending_units.get(node_id, [])
            if pending:
                return pending[0] == unit_id
            return True
        elif kind == "buffer":
            buf = self.buffers.get(node_id)
            if not buf or not buf.occupants:
                return False
            return buf.occupants[0] == unit_id
        elif kind == "station":
            st = self.stations.get(node_id)
            if not st:
                return False
            if st.has_output_units():
                return st.output_buffer[0] == unit_id
            if st.is_blocked:
                return st.blocked_unit_id == unit_id
            if st.current_unit_id == unit_id and not st.is_busy:
                return True
            return False
        return True

    def _try_dispatch_pending_orders(self, k: EventKernel) -> None:
        if not self.pending_transport_orders:
            return

        unconstrained = len(self.vehicles) == 0
        available_vehicles = [v for v in self.vehicles.values() if v.is_available()]
        if not unconstrained and not available_vehicles:
            return

        dispatched_order_ids: list[str] = []

        for order_id in list(self.pending_transport_orders):
            order = self.transport_orders[order_id]
            if order.state != TransportOrderState.PENDING:
                dispatched_order_ids.append(order_id)
                continue

            unit = self.units[order.unit_id]

            if not self._can_unit_depart(order.source_node_id, unit.id):
                continue

            candidates = self._get_candidate_routes_for_unit(order.source_node_id, unit)
            if not candidates:
                continue

            decision = self.dispatch_policy.select_dispatch(
                order=order,
                unit=unit,
                candidate_routes=candidates,
                available_vehicles=available_vehicles,
                active_route_occupancy=self.active_route_occupancy,
                node_distance_fn=self._compute_node_distance,
                can_accept_fn=self._can_accept,
                unconstrained=unconstrained,
            )

            if decision is None:
                continue

            dispatched_order_ids.append(order_id)
            if decision.vehicle is not None:
                available_vehicles.remove(decision.vehicle)

            self._execute_dispatch_decision(k, decision)

            if not unconstrained and not available_vehicles:
                break

        for oid in dispatched_order_ids:
            if oid in self.pending_transport_orders:
                self.pending_transport_orders.remove(oid)

    def _execute_dispatch_decision(self, k: EventKernel, decision: DispatchDecision) -> None:
        order = decision.order
        route = decision.route
        vehicle = decision.vehicle
        target_id = route.target_node_id

        order.target_node_id = target_id
        self.in_flight_to[target_id] += 1
        self.active_route_occupancy[route.id] = self.active_route_occupancy.get(route.id, 0) + 1

        order.dispatch(
            vehicle_id=vehicle.id if vehicle else None,
            route_id=route.id,
            time_ns=k.current_time_ns,
        )

        if vehicle is None:
            self._begin_transport(k, order, route, None)
        else:
            reposition_time_ns = decision.pickup_distance_ns
            if vehicle.speed_multiplier > 0:
                reposition_time_ns = max(0, int(round(reposition_time_ns / vehicle.speed_multiplier)))

            if reposition_time_ns == 0:
                self._begin_transport(k, order, route, vehicle)
            else:
                vehicle.start_repositioning(
                    order_id=order.id,
                    target_node_id=order.source_node_id,
                    time_ns=k.current_time_ns,
                )
                k.schedule(
                    time_ns=k.current_time_ns + reposition_time_ns,
                    priority=EventPriority.COMPLETION,
                    event_type="VEHICLE_ARRIVED_AT_PICKUP",
                    payload={
                        "vehicle_id": vehicle.id,
                        "order_id": order.id,
                        "route_id": route.id,
                    },
                )

    def _begin_transport(
        self,
        k: EventKernel,
        order: TransportOrder,
        route: RouteConfig,
        vehicle: Vehicle | None,
    ) -> None:
        unit = self.units[order.unit_id]
        self._remove_unit_from_node(order.source_node_id, unit.id, k.current_time_ns)
        order.pickup(k.current_time_ns)
        unit.record_transition(
            time_ns=k.current_time_ns,
            state=ProductionUnitState.IN_TRANSPORT,
            location=route.id,
        )

        if vehicle is None:
            k.schedule(
                time_ns=k.current_time_ns + route.transit_time_ns,
                priority=EventPriority.COMPLETION,
                event_type="ARRIVAL_AT_NODE",
                payload={
                    "unit_id": unit.id,
                    "node_id": route.target_node_id,
                    "order_id": order.id,
                    "route_id": route.id,
                },
            )
        else:
            effective_transit = route.transit_time_ns
            if vehicle.speed_multiplier > 0:
                effective_transit = max(1, int(round(effective_transit / vehicle.speed_multiplier)))

            vehicle.start_transport(
                order_id=order.id,
                unit_id=unit.id,
                route_id=route.id,
                time_ns=k.current_time_ns,
            )
            k.schedule(
                time_ns=k.current_time_ns + effective_transit,
                priority=EventPriority.COMPLETION,
                event_type="ARRIVAL_AT_NODE",
                payload={
                    "unit_id": unit.id,
                    "node_id": route.target_node_id,
                    "order_id": order.id,
                    "route_id": route.id,
                    "vehicle_id": vehicle.id,
                },
            )

    def _remove_unit_from_node(self, node_id: str, unit_id: str, time_ns: int) -> None:
        kind = self.nodes_by_id[node_id].kind
        if kind == "source":
            if unit_id in self.source_pending_units.get(node_id, []):
                self.source_pending_units[node_id].remove(unit_id)
        elif kind == "buffer":
            buf = self.buffers[node_id]
            if buf.occupants and buf.occupants[0] == unit_id:
                buf.pop_unit()
            elif unit_id in buf.occupants:
                buf.occupants.remove(unit_id)
        elif kind == "station":
            st = self.stations[node_id]
            if st.has_output_units() and st.output_buffer[0] == unit_id:
                st.pop_output_unit()
                if st.is_blocked:
                    blocked_uid = st.blocked_unit_id
                    assert blocked_uid is not None
                    st.end_blocking(time_ns)
                    st.enqueue_output_unit(blocked_uid)
                    self.units[blocked_uid].record_transition(
                        time_ns=time_ns,
                        state=ProductionUnitState.IN_STATION,
                        location=node_id,
                        station_id=node_id,
                    )
            elif st.is_blocked and st.blocked_unit_id == unit_id:
                st.end_blocking(time_ns)
            elif st.current_unit_id == unit_id:
                st.current_unit_id = None

    def _handle_vehicle_arrived_at_pickup(self, k: EventKernel, event: ScheduledEvent) -> None:
        vehicle_id = event.payload["vehicle_id"]
        order_id = event.payload["order_id"]
        route_id = event.payload["route_id"]

        vehicle = self.vehicles[vehicle_id]
        order = self.transport_orders[order_id]
        route = self.topology.routes_by_id[route_id]

        vehicle.arrive_at_pickup(order.source_node_id, k.current_time_ns)
        self._begin_transport(k, order, route, vehicle)
        self._try_dispatch_pending_orders(k)

    def _handle_release(self, k: EventKernel, event: ScheduledEvent) -> None:
        unit_id = event.payload["unit_id"]
        source_id = event.payload["source_id"]
        unit = self.units[unit_id]
        unit.record_transition(
            time_ns=k.current_time_ns,
            state=ProductionUnitState.RELEASED,
            location=source_id,
        )
        self.source_pending_units[source_id].append(unit_id)
        self._create_transport_order(unit_id, source_id, k.current_time_ns)
        self._try_dispatch_pending_orders(k)

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
        self._create_transport_order(unit_id, node_id, k.current_time_ns)
        self._try_dispatch_pending_orders(k)
        self._try_pull_upstream(k, node_id)

    def _try_pull_upstream(self, k: EventKernel, node_id: str, visited: set[str] | None = None) -> None:
        if visited is None:
            visited = set()
        if node_id in visited:
            return
        visited.add(node_id)
        self._try_dispatch_pending_orders(k)

    def _can_acquire_worker_requirements(
        self, reqs: list[dict[str, Any]], time_ns: int
    ) -> tuple[bool, list[dict[str, Any]]]:
        allocated_workers: list[dict[str, Any]] = []
        temp_worker_allocations: dict[str, int] = {}

        for req in reqs:
            needed_count = req.get("count", 1)
            target_worker_id = req.get("worker_id")
            target_qual = req.get("qualification")

            if target_worker_id is not None:
                w = self.workers.get(target_worker_id)
                if not w or not w.is_available(time_ns):
                    return False, []
                curr_allocated = temp_worker_allocations.get(w.id, 0)
                if w.available_capacity(time_ns) - curr_allocated < needed_count:
                    return False, []
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
                    return False, []

        return True, allocated_workers

    def _can_acquire_resources(
        self, op: Operation, station_id: str, time_ns: int
    ) -> tuple[bool, list[str], list[dict[str, Any]]]:
        allocated_machines: list[str] = []
        for m_id in op.required_machines:
            mach = self.machines.get(m_id)
            if not mach or not mach.can_allocate(1, time_ns):
                return False, [], []
            allocated_machines.append(m_id)

        can_workers, allocated_workers = self._can_acquire_worker_requirements(op.required_workers, time_ns)
        if not can_workers:
            return False, [], []

        return True, allocated_machines, allocated_workers

    def _compute_effective_operation_duration(self, op: Operation, time_ns: int) -> int:
        if not op.required_machines:
            return op.duration_ns
        max_duration = 0
        for m_id in op.required_machines:
            mach = self.machines.get(m_id)
            if mach:
                mach.update_metrics(time_ns)
                mode_info = mach.modes.get(mach.operating_mode, {})
                mode_mult = float(mode_info.get("cycle_time_multiplier", 1.0)) if isinstance(mode_info, dict) else float(getattr(mode_info, "cycle_time_multiplier", 1.0))
                cycle_factor = 0.0
                if mach.degradation_policy:
                    cycle_factor = float(mach.degradation_policy.get("cycle_time_factor", 0.0))
                dur_mult = mode_mult * (1.0 + cycle_factor * (1.0 - mach.health))
                eff_dur = max(1, int(round(op.duration_ns * dur_mult)))
                if eff_dur > max_duration:
                    max_duration = eff_dur
        return max_duration if max_duration > 0 else op.duration_ns

    def _compute_effective_defect_probability(self, op: Operation, time_ns: int) -> float:
        effective_prob = op.defect_probability
        for m_id in op.required_machines:
            mach = self.machines.get(m_id)
            if mach:
                mach.update_metrics(time_ns)
                mode_info = mach.modes.get(mach.operating_mode, {})
                mode_defect_mult = float(mode_info.get("defect_probability_multiplier", 1.0)) if isinstance(mode_info, dict) else float(getattr(mode_info, "defect_probability_multiplier", 1.0))
                defect_factor = 0.0
                if mach.degradation_policy:
                    defect_factor = float(mach.degradation_policy.get("defect_probability_factor", 0.0))
                effective_prob = min(1.0, (effective_prob + defect_factor * (1.0 - mach.health)) * mode_defect_mult)
        return effective_prob

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
                if waiter.get("is_resuming"):
                    rem_dur = waiter.get("remaining_duration_ns", op.duration_ns)
                    st.record_resume()
                elif waiter.get("is_restarting"):
                    rem_dur = self._compute_effective_operation_duration(op, time_ns)
                    st.record_restart()
                else:
                    rem_dur = waiter.get("remaining_duration_ns")
                    if rem_dur is None:
                        rem_dur = self._compute_effective_operation_duration(op, time_ns)
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
        self._try_allocate_pending_maintenance(k.current_time_ns)
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

        self._try_allocate_pending_maintenance(k.current_time_ns)
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
        self._try_allocate_pending_maintenance(k.current_time_ns)
        self._try_allocate_pending_resources(k.current_time_ns)

    def _handle_disruption_start(self, k: EventKernel, event: ScheduledEvent) -> None:
        mach_id = event.payload["machine_id"]
        mach = self.machines[mach_id]
        disruption = event.payload.get("disruption", event.payload)
        dur_ns = disruption.get("duration_ns", event.payload.get("duration_ns", 0))
        repaired_health = disruption.get("repaired_health", event.payload.get("repaired_health"))
        req_workers = disruption.get("required_workers", event.payload.get("required_workers", []))

        mach.start_failure(k.current_time_ns)
        active_stations = [
            s_id for s_id, a_op in list(self.active_operations.items())
            if mach_id in a_op["machines"]
        ]
        for s_id in active_stations:
            self._interrupt_operation(s_id, k.current_time_ns)

        can_acq, worker_allocs = self._can_acquire_worker_requirements(req_workers, k.current_time_ns)
        if can_acq:
            for alloc in worker_allocs:
                for _ in range(alloc["count"]):
                    self.workers[alloc["worker_id"]].allocate("maintenance", mach_id, "disruption", k.current_time_ns)
            token = self.kernel.sequence_counter + 1
            self.active_maintenances[mach_id] = {
                "machine_id": mach_id,
                "type": "disruption",
                "token": token,
                "workers": worker_allocs,
                "repaired_health": repaired_health,
            }
            k.schedule(
                time_ns=k.current_time_ns + dur_ns,
                priority=EventPriority.COMPLETION,
                event_type="COMPLETE_REPAIR",
                payload={"machine_id": mach_id, "token": token},
            )
        else:
            self.maintenance_waiters.append({
                "machine_id": mach_id,
                "type": "disruption",
                "duration_ns": dur_ns,
                "repaired_health": repaired_health,
                "required_workers": req_workers,
                "waiting_since_ns": k.current_time_ns,
            })

    def _handle_machine_failure(self, k: EventKernel, event: ScheduledEvent) -> None:
        mach_id = event.payload["machine_id"]
        mach = self.machines[mach_id]
        if mach.is_failed or mach.is_in_maintenance:
            return

        mach.start_failure(k.current_time_ns)
        active_stations = [
            s_id for s_id, a_op in list(self.active_operations.items())
            if mach_id in a_op["machines"]
        ]
        for s_id in active_stations:
            self._interrupt_operation(s_id, k.current_time_ns)

        f_policy = mach.failure_policy or {}
        repaired_health = f_policy.get("repaired_health", 1.0)
        req_workers = f_policy.get("required_workers", [])
        if f_policy.get("mttr_ns", 0) > 0:
            import math
            u_rep = self.random_stream.draw_float("machine_repair", mach.id, "duration")
            u_rep = max(1e-10, min(1.0 - 1e-10, u_rep))
            dur_ns = max(1, int(-math.log(1.0 - u_rep) * f_policy["mttr_ns"]))
        else:
            dur_ns = f_policy.get("repair_duration_ns", 0)

        can_acq, worker_allocs = self._can_acquire_worker_requirements(req_workers, k.current_time_ns)
        if can_acq:
            for alloc in worker_allocs:
                for _ in range(alloc["count"]):
                    self.workers[alloc["worker_id"]].allocate("maintenance", mach_id, "failure_repair", k.current_time_ns)
            token = self.kernel.sequence_counter + 1
            self.active_maintenances[mach_id] = {
                "machine_id": mach_id,
                "type": "failure_repair",
                "token": token,
                "workers": worker_allocs,
                "repaired_health": repaired_health,
            }
            k.schedule(
                time_ns=k.current_time_ns + dur_ns,
                priority=EventPriority.COMPLETION,
                event_type="COMPLETE_REPAIR",
                payload={"machine_id": mach_id, "token": token},
            )
        else:
            self.maintenance_waiters.append({
                "machine_id": mach_id,
                "type": "failure_repair",
                "duration_ns": dur_ns,
                "repaired_health": repaired_health,
                "required_workers": req_workers,
                "waiting_since_ns": k.current_time_ns,
            })

    def _handle_complete_repair(self, k: EventKernel, event: ScheduledEvent) -> None:
        mach_id = event.payload["machine_id"]
        token = event.payload.get("token")
        active_m = self.active_maintenances.get(mach_id)
        if not active_m or (token is not None and active_m.get("token") != token):
            return
        self.active_maintenances.pop(mach_id)

        for alloc in active_m["workers"]:
            w_id = alloc["worker_id"]
            for _ in range(alloc["count"]):
                self.workers[w_id].release("maintenance", mach_id, active_m.get("type", "repair"), k.current_time_ns, completed=True)

        mach = self.machines[mach_id]
        repaired_health = active_m.get("repaired_health")
        mach.end_failure(k.current_time_ns, restored_health=repaired_health)

        self._schedule_next_failure(k, mach)

        self._try_allocate_pending_maintenance(k.current_time_ns)
        self._try_allocate_pending_resources(k.current_time_ns)
        for st_id, st in self.stations.items():
            if not st.is_busy and not st.is_blocked:
                self._try_pull_upstream(k, st_id)

    def _trigger_maintenance(self, k: EventKernel, mach: Machine) -> None:
        if mach.is_in_maintenance or mach.is_failed:
            return
        if len(mach.active_allocations) > 0:
            return

        mach.start_maintenance(k.current_time_ns)
        m_policy = mach.maintenance_policy or {}
        dur_ns = m_policy.get("duration_ns", 0)
        restored_health = m_policy.get("restored_health", 1.0)
        req_workers = m_policy.get("required_workers", [])

        can_acq, worker_allocs = self._can_acquire_worker_requirements(req_workers, k.current_time_ns)
        if can_acq:
            for alloc in worker_allocs:
                for _ in range(alloc["count"]):
                    self.workers[alloc["worker_id"]].allocate("maintenance", mach.id, "maintenance", k.current_time_ns)
            token = self.kernel.sequence_counter + 1
            self.active_maintenances[mach.id] = {
                "machine_id": mach.id,
                "type": "maintenance",
                "token": token,
                "workers": worker_allocs,
                "restored_health": restored_health,
            }
            k.schedule(
                time_ns=k.current_time_ns + dur_ns,
                priority=EventPriority.COMPLETION,
                event_type="COMPLETE_MAINTENANCE",
                payload={"machine_id": mach.id, "token": token},
            )
        else:
            self.maintenance_waiters.append({
                "machine_id": mach.id,
                "type": "maintenance",
                "duration_ns": dur_ns,
                "restored_health": restored_health,
                "required_workers": req_workers,
                "waiting_since_ns": k.current_time_ns,
            })

    def _handle_maintenance_trigger(self, k: EventKernel, event: ScheduledEvent) -> None:
        mach_id = event.payload["machine_id"]
        mach = self.machines[mach_id]
        self._trigger_maintenance(k, mach)
        m_policy = mach.maintenance_policy or {}
        interval_ns = m_policy.get("interval_ns", 0)
        if interval_ns > 0:
            k.schedule(
                time_ns=k.current_time_ns + interval_ns,
                priority=EventPriority.RESOURCE,
                event_type="MAINTENANCE_TRIGGER",
                payload={"machine_id": mach.id},
            )

    def _handle_complete_maintenance(self, k: EventKernel, event: ScheduledEvent) -> None:
        mach_id = event.payload["machine_id"]
        token = event.payload.get("token")
        active_m = self.active_maintenances.get(mach_id)
        if not active_m or (token is not None and active_m.get("token") != token):
            return
        self.active_maintenances.pop(mach_id)

        for alloc in active_m["workers"]:
            w_id = alloc["worker_id"]
            for _ in range(alloc["count"]):
                self.workers[w_id].release("maintenance", mach_id, "maintenance", k.current_time_ns, completed=True)

        mach = self.machines[mach_id]
        restored_health = active_m.get("restored_health")
        mach.end_maintenance(k.current_time_ns, restored_health=restored_health)

        self._try_allocate_pending_maintenance(k.current_time_ns)
        self._try_allocate_pending_resources(k.current_time_ns)
        for st_id, st in self.stations.items():
            if not st.is_busy and not st.is_blocked:
                self._try_pull_upstream(k, st_id)

    def _try_allocate_pending_maintenance(self, time_ns: int) -> None:
        if not self.maintenance_waiters:
            return
        self.maintenance_waiters.sort(key=lambda w: w["waiting_since_ns"])
        allocated_indices: list[int] = []
        for idx, waiter in enumerate(self.maintenance_waiters):
            mach_id = waiter["machine_id"]
            req_workers = waiter["required_workers"]
            can_acq, worker_allocs = self._can_acquire_worker_requirements(req_workers, time_ns)
            if can_acq:
                allocated_indices.append(idx)
                for alloc in worker_allocs:
                    for _ in range(alloc["count"]):
                        self.workers[alloc["worker_id"]].allocate("maintenance", mach_id, waiter["type"], time_ns)
                token = self.kernel.sequence_counter + 1
                self.active_maintenances[mach_id] = {
                    "machine_id": mach_id,
                    "type": waiter["type"],
                    "token": token,
                    "workers": worker_allocs,
                    "repaired_health": waiter.get("repaired_health"),
                    "restored_health": waiter.get("restored_health"),
                }
                ev_type = "COMPLETE_REPAIR" if waiter["type"] in ("disruption", "failure_repair") else "COMPLETE_MAINTENANCE"
                self.kernel.schedule(
                    time_ns=time_ns + waiter["duration_ns"],
                    priority=EventPriority.COMPLETION,
                    event_type=ev_type,
                    payload={"machine_id": mach_id, "token": token},
                )
        for idx in reversed(allocated_indices):
            self.maintenance_waiters.pop(idx)

    def _schedule_next_failure(self, k: EventKernel, mach: Machine) -> None:
        fp = mach.failure_policy or {}
        dp = mach.degradation_policy or {}
        mttf_ns = fp.get("mttf_ns", 0)
        hazard_rate = float(fp.get("hazard_rate_per_s", 0.0)) or float(dp.get("failure_hazard_rate_per_s", 0.0))
        if mttf_ns <= 0 and hazard_rate <= 0.0:
            return

        import math
        roll = self.random_stream.draw_float("machine_failure", mach.id, "ttf")
        u = max(1e-10, min(1.0 - 1e-10, roll))
        mode_info = mach.modes.get(mach.operating_mode, {})
        mode_mult = float(mode_info.get("hazard_multiplier", 1.0)) if isinstance(mode_info, dict) else float(getattr(mode_info, "hazard_multiplier", 1.0))
        hazard_factor = float(fp.get("health_hazard_factor", 0.0)) or float(dp.get("hazard_health_factor", 0.0))
        if mttf_ns > 0:
            effective_mttf = mttf_ns / (mode_mult * (1.0 + hazard_factor * (1.0 - mach.health)))
            t_ns = max(1, int(-math.log(1.0 - u) * effective_mttf))
        else:
            effective_hazard = hazard_rate * mode_mult * (1.0 + hazard_factor * (1.0 - mach.health))
            if effective_hazard <= 0.0:
                return
            t_sec = -math.log(1.0 - u) / effective_hazard
            t_ns = max(1, int(t_sec * 1_000_000_000))

        k.schedule(
            time_ns=k.current_time_ns + t_ns,
            priority=EventPriority.FAILURE,
            event_type="MACHINE_FAILURE",
            payload={"machine_id": mach.id},
        )

    def _handle_station_arrival(self, k: EventKernel, unit_id: str, node_id: str) -> None:
        st = self.stations[node_id]
        assert st.can_accept(), f"Station {node_id} accepted unit {unit_id} while busy/blocked"
        st.current_unit_id = unit_id
        unit = self.units[unit_id]

        if unit.is_in_rework and unit.rework_operation_id and unit.rework_operation_id in st.operations:
            op = st.operations[unit.rework_operation_id]
            op_index = list(st.operations.keys()).index(unit.rework_operation_id)
        elif unit.is_in_rework and any(op.restores_quality for op in st.operations.values()):
            op = next(op for op in st.operations.values() if op.restores_quality)
            op_index = list(st.operations.keys()).index(op.id)
        elif unit.is_in_rework and len(st.operations) == 1:
            op = list(st.operations.values())[0]
            op_index = 0
        elif unit.variant in self.process_plans:
            plan = self.process_plans[unit.variant]
            step = plan.steps[unit.process_step_index]
            op = st.operations[step.operation_id]
            op_index = list(st.operations.keys()).index(step.operation_id)
        else:
            op = list(st.operations.values())[0]
            op_index = 0

        self.units[unit_id].record_transition(
            time_ns=k.current_time_ns,
            state=ProductionUnitState.IN_STATION,
            location=node_id,
            station_id=node_id,
            operation_id=op.id,
        )

        can_acq, mach_ids, worker_allocs = self._can_acquire_resources(op, node_id, k.current_time_ns)
        eff_dur = self._compute_effective_operation_duration(op, k.current_time_ns)
        if can_acq:
            token = self._acquire_resources(
                station_id=node_id,
                unit_id=unit_id,
                op=op,
                op_index=op_index,
                remaining_duration_ns=eff_dur,
                mach_ids=mach_ids,
                worker_allocs=worker_allocs,
                time_ns=k.current_time_ns,
            )
            st.start_operation(unit_id, op.id, k.current_time_ns)
            k.schedule(
                time_ns=k.current_time_ns + eff_dur,
                priority=EventPriority.COMPLETION,
                event_type="COMPLETE_OPERATION",
                payload={"unit_id": unit_id, "station_id": node_id, "op_index": op_index, "token": token},
            )
        else:
            st.start_waiting(k.current_time_ns)
            self.resource_waiters.append({
                "station_id": node_id,
                "unit_id": unit_id,
                "op_index": op_index,
                "waiting_since_ns": k.current_time_ns,
                "remaining_duration_ns": eff_dur,
            })

    def _handle_arrival_at_node(self, k: EventKernel, event: ScheduledEvent) -> None:
        unit_id = event.payload["unit_id"]
        node_id = event.payload["node_id"]
        order_id = event.payload.get("order_id")
        route_id = event.payload.get("route_id")
        vehicle_id = event.payload.get("vehicle_id")

        self.in_flight_to[node_id] -= 1
        if route_id and route_id in self.active_route_occupancy:
            self.active_route_occupancy[route_id] = max(0, self.active_route_occupancy[route_id] - 1)

        if vehicle_id and vehicle_id in self.vehicles:
            vehicle = self.vehicles[vehicle_id]
            vehicle.arrive_at_destination(node_id, k.current_time_ns)

        if order_id and order_id in self.transport_orders:
            self.transport_orders[order_id].complete(k.current_time_ns)

        kind = self.nodes_by_id[node_id].kind
        if kind == "sink":
            self._handle_sink_arrival(k, unit_id, node_id)
        elif kind == "buffer":
            self._handle_buffer_arrival(k, unit_id, node_id)
        elif kind == "station":
            self._handle_station_arrival(k, unit_id, node_id)

        self._try_dispatch_pending_orders(k)

    def _route_or_buffer_unit(self, k: EventKernel, station_id: str, unit_id: str) -> None:
        st = self.stations[station_id]
        unit = self.units[unit_id]

        if st.has_output_space():
            st.current_unit_id = None
            st.enqueue_output_unit(unit_id)
            unit.record_transition(
                time_ns=k.current_time_ns,
                state=ProductionUnitState.IN_STATION,
                location=station_id,
                station_id=station_id,
            )
        else:
            st.start_blocking(unit_id, k.current_time_ns)
            unit.record_transition(
                time_ns=k.current_time_ns,
                state=ProductionUnitState.BLOCKED,
                location=station_id,
                station_id=station_id,
            )

        self._create_transport_order(unit_id, station_id, k.current_time_ns)
        self._try_dispatch_pending_orders(k)
        self._try_allocate_pending_resources(k.current_time_ns)
        self._try_pull_upstream(k, station_id)

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
        unit = self.units[unit_id]

        self._release_resources(station_id, k.current_time_ns, completed=True)
        st.complete_operation(current_op.id, k.current_time_ns)

        was_in_rework = unit.is_in_rework

        # 1. Defect generation (addressed by unit and operation for counterfactual consistency)
        eff_defect_prob = self._compute_effective_defect_probability(current_op, k.current_time_ns)
        if eff_defect_prob > 0.0:
            defect_roll = self.random_stream.draw_float("quality", f"{unit.id}:{current_op.id}", "defect")
            if defect_roll < eff_defect_prob:
                defect_name = current_op.defect_name or f"defect_{current_op.id}"
                target_state = current_op.target_quality_state or defect_name
                unit.alter_quality(target_state=target_state, defect=defect_name)

        # Check condition threshold maintenance for machines involved
        for m_id in current_op.required_machines:
            mach = self.machines.get(m_id)
            if mach and mach.maintenance_policy:
                trigger = mach.maintenance_policy.get("trigger", "condition_threshold")
                thresh = float(mach.maintenance_policy.get("health_threshold", 0.0))
                if trigger == "condition_threshold" and mach.health <= thresh:
                    self._trigger_maintenance(k, mach)

        # 2. Quality restoration (rework completion)
        if current_op.restores_quality:
            rework_success = True
            if current_op.rework_success_probability < 1.0:
                success_roll = self.random_stream.draw_float("quality", f"{unit.id}:{current_op.id}", "rework_success")
                rework_success = success_roll < current_op.rework_success_probability
            if rework_success:
                unit.restore_quality()
                unit.is_in_rework = False
                unit.rework_target_station_id = None
                unit.rework_operation_id = None

        # 3. Inspection
        if current_op.inspection:
            insp = current_op.inspection
            sensitivity = float(insp.get("sensitivity", 1.0))
            fp_rate = float(insp.get("false_positive_rate", 0.0))
            disp_on_defect = insp.get("disposition_on_defect", "scrap")
            max_reworks = int(insp.get("max_reworks", 1))

            is_defect_detected = False
            if unit.is_defective:
                detection_roll = self.random_stream.draw_float("inspection", f"{unit.id}:{current_op.id}", "detection")
                if detection_roll < sensitivity:
                    is_defect_detected = True
            else:
                fp_roll = self.random_stream.draw_float("inspection", f"{unit.id}:{current_op.id}", "false_positive")
                if fp_roll < fp_rate:
                    is_defect_detected = True

            if is_defect_detected:
                result = "defect_detected"
                if disp_on_defect == "rework" and unit.rework_count >= max_reworks:
                    disposition = "scrap"
                else:
                    disposition = disp_on_defect
            else:
                result = "nominal"
                disposition = "pass"

            finding = QualityFinding(
                time_ns=k.current_time_ns,
                unit_id=unit_id,
                station_id=station_id,
                operation_id=current_op.id,
                result=result,
                disposition=disposition,
            )
            unit.findings.append(finding)

            if disposition == "scrap":
                unit.record_transition(
                    time_ns=k.current_time_ns,
                    state=ProductionUnitState.TERMINAL,
                    location="terminal",
                    station_id=station_id,
                    operation_id=current_op.id,
                )
                st.scrapped_count += 1
                st.current_unit_id = None
                self._try_pull_upstream(k, station_id)
                self._try_allocate_pending_resources(k.current_time_ns)
                return

            elif disposition == "rework":
                unit.is_in_rework = True
                unit.rework_count += 1
                unit.rework_target_station_id = insp.get("rework_station_id")
                unit.rework_operation_id = insp.get("rework_operation_id")
                self._route_or_buffer_unit(k, station_id, unit_id)
                return

        if unit.variant in self.process_plans:
            if not was_in_rework:
                unit.process_step_index += 1
            self._route_or_buffer_unit(k, station_id, unit_id)
            return

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
            eff_dur = self._compute_effective_operation_duration(next_op, k.current_time_ns)
            if can_acq:
                token = self._acquire_resources(
                    station_id=station_id,
                    unit_id=unit_id,
                    op=next_op,
                    op_index=op_index + 1,
                    remaining_duration_ns=eff_dur,
                    mach_ids=mach_ids,
                    worker_allocs=worker_allocs,
                    time_ns=k.current_time_ns,
                )
                st.start_operation(unit_id, next_op.id, k.current_time_ns)
                k.schedule(
                    time_ns=k.current_time_ns + eff_dur,
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
                    "remaining_duration_ns": eff_dur,
                })
            self._try_allocate_pending_resources(k.current_time_ns)
            return

        # Last operation completed for this unit:
        self._route_or_buffer_unit(k, station_id, unit_id)

    def _is_terminal_condition_met(self, k: EventKernel) -> bool:
        if self.cfg.episode.end_condition.type == "all_units_terminal":
            return all(u.state == ProductionUnitState.TERMINAL for u in self.units.values())
        return False

    @classmethod
    def create(cls, cfg: SimulationConfig) -> EpisodeEngine:
        units: dict[str, ProductionUnit] = {
            u_cfg.id: ProductionUnit(
                id=u_cfg.id,
                variant=u_cfg.variant,
                due_date_ns=u_cfg.due_date_ns,
                quality_state=u_cfg.quality_state,
            )
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
                            defect_probability=op.defect_probability,
                            defect_name=op.defect_name,
                            target_quality_state=op.target_quality_state,
                            restores_quality=op.restores_quality,
                            rework_success_probability=op.rework_success_probability,
                            inspection=op.inspection.model_dump() if op.inspection else None,
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
            modes = {k: v.model_dump() for k, v in m_cfg.modes.items()}
            deg_policy = m_cfg.degradation.model_dump() if m_cfg.degradation else None
            maint_policy = m_cfg.maintenance.model_dump() if m_cfg.maintenance else None
            insp_policy = m_cfg.inspection.model_dump() if m_cfg.inspection else None
            fail_policy = m_cfg.failure.model_dump() if m_cfg.failure else None
            disruptions = [d.model_dump() for d in m_cfg.planned_disruptions]

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
                health=m_cfg.initial_health,
                operating_mode=m_cfg.operating_mode,
                modes=modes,
                degradation_policy=deg_policy,
                maintenance_policy=maint_policy,
                inspection_policy=insp_policy,
                failure_policy=fail_policy,
                planned_disruptions=disruptions,
                physical_state=dict(m_cfg.physical_state),
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
            # Schedule planned disruptions
            for d in m_cfg.planned_disruptions:
                if d.start_time_ns >= cfg.episode.start_time_ns:
                    kernel.schedule(
                        time_ns=d.start_time_ns,
                        priority=EventPriority.RESOURCE,
                        event_type="DISRUPTION_START",
                        payload={"machine_id": m_cfg.id, "disruption": d.model_dump()},
                    )
            # Schedule scheduled maintenance
            if m_cfg.maintenance and m_cfg.maintenance.trigger == "scheduled":
                interval_ns = m_cfg.maintenance.interval_ns
                if interval_ns and interval_ns > 0:
                    first_maint_t = cfg.episode.start_time_ns + interval_ns
                    kernel.schedule(
                        time_ns=first_maint_t,
                        priority=EventPriority.RESOURCE,
                        event_type="MAINTENANCE_TRIGGER",
                        payload={"machine_id": m_cfg.id, "trigger_type": "scheduled"},
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

        vehicles = _create_vehicles_from_config(cfg)

        topology = MaterialFlowTopology.from_material_flow(mf)
        domain = SimulationDomainState(
            units=units,
            stations=stations,
            buffers=buffers,
            in_flight_to=in_flight_to,
            source_pending_units=source_pending_units,
            machines=machines,
            workers=workers,
            vehicles=vehicles,
            transport_orders={},
            pending_transport_orders=[],
            active_route_occupancy={r.id: 0 for r in mf.routes},
        )

        engine = cls(
            config=cfg,
            kernel=kernel,
            topology=topology,
            domain=domain,
        )

        for m in machines.values():
            if m.failure_policy:
                engine._schedule_next_failure(kernel, m)

        return engine

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
                        defect_probability=op.defect_probability,
                        defect_name=op.defect_name,
                        target_quality_state=op.target_quality_state,
                        restores_quality=op.restores_quality,
                        rework_success_probability=op.rework_success_probability,
                        inspection=op.inspection.model_dump() if op.inspection else None,
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
            modes = {k: v.model_dump() for k, v in m_cfg.modes.items()}
            deg_policy = m_cfg.degradation.model_dump() if m_cfg.degradation else None
            maint_policy = m_cfg.maintenance.model_dump() if m_cfg.maintenance else None
            insp_policy = m_cfg.inspection.model_dump() if m_cfg.inspection else None
            fail_policy = m_cfg.failure.model_dump() if m_cfg.failure else None
            disruptions = [d.model_dump() for d in m_cfg.planned_disruptions]

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
                health=m_cfg.initial_health,
                operating_mode=m_cfg.operating_mode,
                modes=modes,
                degradation_policy=deg_policy,
                maintenance_policy=maint_policy,
                inspection_policy=insp_policy,
                failure_policy=fail_policy,
                planned_disruptions=disruptions,
                physical_state=dict(m_cfg.physical_state),
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
        maintenance_waiters = list(domain_state.get("maintenance_waiters", []))
        active_maintenances = {k: dict(v) for k, v in domain_state.get("active_maintenances", {}).items()}

        # Restore vehicles
        vehicles = _create_vehicles_from_config(cfg)
        for v_id, v_data in domain_state.get("vehicles", {}).items():
            if v_id in vehicles:
                vehicles[v_id].restore_state(v_data)

        # Restore transport orders
        transport_orders: dict[str, TransportOrder] = {
            oid: TransportOrder.from_snapshot(o_data)
            for oid, o_data in domain_state.get("transport_orders", {}).items()
        }
        pending_transport_orders = list(domain_state.get("pending_transport_orders", []))
        active_route_occupancy = {r.id: 0 for r in mf.routes}
        active_route_occupancy.update(domain_state.get("active_route_occupancy", {}))

        topology = MaterialFlowTopology.from_material_flow(mf)
        domain = SimulationDomainState(
            units=units,
            stations=stations,
            buffers=buffers,
            in_flight_to=in_flight_to,
            source_pending_units=source_pending_units,
            machines=machines,
            workers=workers,
            vehicles=vehicles,
            transport_orders=transport_orders,
            pending_transport_orders=pending_transport_orders,
            active_route_occupancy=active_route_occupancy,
            resource_waiters=resource_waiters,
            active_operations=active_operations,
            maintenance_waiters=maintenance_waiters,
            active_maintenances=active_maintenances,
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
            vehicles={
                v.id: VehicleSnapshot.from_dict(v.to_snapshot())
                for v in self.vehicles.values()
            },
            transport_orders={
                o.id: TransportOrderSnapshot.from_dict(o.to_snapshot())
                for o in self.transport_orders.values()
            },
            pending_transport_orders=list(self.pending_transport_orders),
            active_route_occupancy=dict(self.active_route_occupancy),
            in_flight_to=dict(self.in_flight_to),
            source_pending_units={k: list(v) for k, v in self.source_pending_units.items()},
            resource_waiters=list(self.resource_waiters),
            active_operations={k: dict(v) for k, v in self.active_operations.items()},
            maintenance_waiters=list(self.maintenance_waiters),
            active_maintenances={k: dict(v) for k, v in self.active_maintenances.items()},
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
        for v in self.vehicles.values():
            v.update_metrics(self.kernel.current_time_ns)
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
                due_date_ns=u.due_date_ns,
                process_step_index=u.process_step_index,
                findings=[f.to_dict() for f in u.findings],
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
                total_maintenance_time_ns=m.total_maintenance_time_ns,
                total_failed_time_ns=m.total_failed_time_ns,
                maintenance_count=m.maintenance_count,
                failure_count=m.failure_count,
                health=m.health,
                operating_mode=m.operating_mode,
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

        vehicle_summaries = sorted(
            [
                VehicleSummary(
                    id=v.id,
                    location=v.location,
                    transports_completed=v.transports_completed,
                    total_busy_time_ns=v.total_busy_time_ns,
                    total_idle_time_ns=v.total_idle_time_ns,
                    utilization=v.utilization,
                    pool_id=v.pool_id,
                )
                for v in self.vehicles.values()
            ],
            key=lambda v: v.id,
        )

        transport_order_summaries = sorted(
            [
                TransportOrderSummary(
                    id=o.id,
                    unit_id=o.unit_id,
                    source_node_id=o.source_node_id,
                    target_node_id=o.target_node_id,
                    route_id=o.assigned_route_id,
                    vehicle_id=o.assigned_vehicle_id,
                    state=str(o.state),
                    created_time_ns=o.created_time_ns,
                    dispatched_time_ns=o.dispatched_time_ns,
                    completed_time_ns=o.completed_time_ns,
                )
                for o in self.transport_orders.values()
            ],
            key=lambda o: o.id,
        )

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
            vehicles=vehicle_summaries,
            transport_orders=transport_order_summaries,
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
            vehicles=vehicle_summaries,
            transport_orders=transport_order_summaries,
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

