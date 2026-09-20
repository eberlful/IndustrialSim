from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import heapq
import json
from io import StringIO
from pathlib import Path
from typing import Any, Sequence
from pydantic import TypeAdapter, ValidationError
from ruamel.yaml import YAML

from industrialsim.config import (
    BufferThresholdTriggerConfig,
    DispatchDecisionTriggerConfig,
    MachineDecisionTriggerConfig,
    MaterialFlowConfig,
    NodeConfig,
    PortConfig,
    ProcessPlanConfig,
    RouteConfig,
    RoutingDecisionTriggerConfig,
    SafePointTriggerConfig,
    SimulationConfig,
    StationConfig,
    RewardPolicyConfig,
    HardConstraintsConfig,
    TelemetryConfig,
)
from industrialsim.telemetry import TelemetryManager
from industrialsim.dispatch import (
    BaselineDispatchPolicy,
    DispatchContext,
    DispatchDecision,
)
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
from industrialsim.decisions import (
    BaselineFallbackPolicy,
    BufferObservation,
    BufferOccupantSummary,
    BufferReorderAction,
    BufferTriggerRuntime,
    DecisionAction,
    DecisionBatch,
    DecisionBatchCoordinator,
    DecisionBatchResponse,
    DecisionDiagnosticRecord,
    DecisionProvenance,
    DecisionProvider,
    DecisionRequest,
    DispatchAction,
    DispatchObservation,
    DispatchTriggerRuntime,
    FifoBufferFallbackPolicy,
    MachineModeAction,
    MachineObservation,
    MachineTriggerRuntime,
    MaintenanceAction,
    QualityControlAction,
    QualityControlBounds,
    ReconfigurationAction,
    RouteSummaryObservation,
    RoutingAction,
    RoutingObservation,
    RoutingTriggerRuntime,
    SafePointTriggerRuntime,
    StrategicObservation,
    VehicleSummaryObservation,
    WorkerReassignmentAction,
    validate_decision_batch_response,
)
from industrialsim.kernel import EventKernel, EventPriority, ScheduledEvent
from industrialsim.random import SemanticRandomStream
from industrialsim.deadlock import DeadlockDiagnosis, analyze_deadlock
from industrialsim.audit import (
    AuditLogger,
    AuditRecord,
    RunArtifactExistsError,
    RunArtifactWriter,
    RunInspection,
    inspect,
    inspect_run,
    load_audit_log,
    collect_runtime_metadata,
    collect_library_metadata,
    collect_calibration_metadata,
)


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
    decision_batches: list[dict[str, Any]] = field(default_factory=list)
    decision_diagnostics: list[dict[str, Any]] = field(default_factory=list)
    is_aborted: bool = False
    abort_reason: str | None = None
    is_deadlocked: bool = False
    deadlock_diagnosis: dict[str, Any] | None = None
    total_cost: float = 0.0
    total_strategic_cost: float = 0.0
    raw_metrics: dict[str, Any] = field(default_factory=dict)
    reward: float | None = None
    reward_breakdown: dict[str, float] = field(default_factory=dict)
    hard_constraints: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        res = {
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
            "decision_batches": list(self.decision_batches),
            "decision_diagnostics": list(self.decision_diagnostics),
            "total_cost": self.total_cost,
            "total_strategic_cost": self.total_strategic_cost,
            "raw_metrics": dict(self.raw_metrics),
            "reward": self.reward,
            "reward_breakdown": dict(self.reward_breakdown),
            "hard_constraints": dict(self.hard_constraints),
            "result_hash": self.result_hash,
        }
        if self.is_aborted:
            res["is_aborted"] = True
            res["abort_reason"] = self.abort_reason
        if self.is_deadlocked or self.status == "deadlocked":
            res["status"] = "deadlocked"
            res["is_deadlocked"] = True
            if self.deadlock_diagnosis is not None:
                res["deadlock_diagnosis"] = dict(self.deadlock_diagnosis)
        return res


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
    decision_batches: list[dict[str, Any]] | None = None,
    decision_diagnostics: list[dict[str, Any]] | None = None,
    deadlock_diagnosis: dict[str, Any] | None = None,
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
    if decision_batches:
        data["decision_batches"] = decision_batches
    if decision_diagnostics:
        data["decision_diagnostics"] = decision_diagnostics
    if deadlock_diagnosis:
        data["deadlock_diagnosis"] = deadlock_diagnosis
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
        # Check directed path first
        dist = self.find_shortest_path_distance(from_node, to_node, directed=True)
        if dist is not None:
            return dist
        # Fall back to physical route connectivity for empty vehicle repositioning:
        # Source nodes have in-degree 0 in the directed material flow graph (sources
        # cannot have input ports per schema), so returning to pickup traverses the
        # physical transport connectivity between nodes.
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
    reserved_route_occupancy: dict[str, int] = field(default_factory=dict)
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
        decision_provider: DecisionProvider | None = None,
        audit_logger: AuditLogger | None = None,
        telemetry_manager: TelemetryManager | None = None,
    ) -> None:
        self.cfg = config
        self.kernel = kernel
        self.topology = topology
        self.domain = domain
        self.random_occurrence_counters = dict(random_occurrence_counters or {})
        self.plugin_metadata = plugin_metadata or {}
        self.decision_provider = decision_provider
        self.episode_id = f"ep-{self.cfg.seed}"
        self.decision_coordinator = DecisionBatchCoordinator(episode_id=self.episode_id)
        self.audit_logger = audit_logger or AuditLogger()
        self.telemetry_manager = (
            telemetry_manager
            if telemetry_manager is not None
            else TelemetryManager(
                output_dir=None,
                config=self.cfg.telemetry,
                episode_id=self.episode_id,
            )
        )
        self.total_strategic_cost: float = 0.0
        self.decision_triggers: dict[str, list[Any]] = {}
        for t in self.cfg.decision_triggers:
            if isinstance(t, BufferThresholdTriggerConfig):
                runtime = BufferTriggerRuntime(config=t)
                self.decision_triggers.setdefault(t.buffer_id, []).append(runtime)
            elif isinstance(t, MachineDecisionTriggerConfig):
                m_runtime = MachineTriggerRuntime(config=t)
                self.decision_triggers.setdefault(t.machine_id, []).append(m_runtime)
            elif isinstance(t, SafePointTriggerConfig):
                s_runtime = SafePointTriggerRuntime(config=t)
                self.decision_triggers.setdefault(t.target_id, []).append(s_runtime)
            elif isinstance(t, RoutingDecisionTriggerConfig):
                r_runtime = RoutingTriggerRuntime(config=t)
                self.decision_triggers.setdefault(t.node_id, []).append(r_runtime)
            elif isinstance(t, DispatchDecisionTriggerConfig):
                d_runtime = DispatchTriggerRuntime(config=t)
                self.decision_triggers.setdefault("dispatch", []).append(d_runtime)
        self.decision_diagnostics: list[dict[str, Any]] = []
        self.decision_batches: list[dict[str, Any]] = []
        self.is_aborted: bool = False
        self.abort_reason: str | None = None
        self.buffer_history: dict[str, list[dict[str, Any]]] = {}
        self.process_plans: dict[str, ProcessPlanConfig] = {
            p.variant: p for p in self.cfg.process_plans
        }
        self.random_stream = SemanticRandomStream(
            root_seed=self.cfg.seed,
            occurrence_counters=self.random_occurrence_counters,
        )
        self.is_deadlocked: bool = False
        self.deadlock_diagnosis: DeadlockDiagnosis | None = None
        self.last_domain_progress_time_ns: int = self.cfg.episode.start_time_ns
        self.max_interval_without_progress_ns: int | None = None
        if self.cfg.deadlock is not None and self.cfg.deadlock.enabled:
            self.max_interval_without_progress_ns = self.cfg.deadlock.max_interval_without_progress_ns

        self.dispatch_policy = dispatch_policy or BaselineDispatchPolicy()

        self._setup_handlers()

    @property
    def is_telemetry_enabled(self) -> bool:
        return self.telemetry_manager.is_enabled

    def enable_telemetry(self) -> None:
        self.telemetry_manager.enable()

    def disable_telemetry(self) -> None:
        self.telemetry_manager.disable()

    def _record_domain_progress(self, time_ns: int) -> None:
        self.last_domain_progress_time_ns = time_ns

    def _terminate_with_deadlock(self, diagnosis: DeadlockDiagnosis) -> None:
        self.is_deadlocked = True
        self.deadlock_diagnosis = diagnosis
        self.audit_logger.record(
            event_type="deadlock",
            simulated_time_ns=self.kernel.current_time_ns,
            episode_id=self.episode_id,
            branch_id=getattr(self.decision_coordinator, "branch_id", None),
            entity_ids=diagnosis.involved_entities,
            details=diagnosis.to_dict(),
        )

    def _record_unit_transition(
        self,
        unit: ProductionUnit,
        state: ProductionUnitState,
        location: str,
        time_ns: int,
        details: dict[str, Any] | None = None,
        station_id: str | None = None,
        operation_id: str | None = None,
    ) -> None:
        self._record_domain_progress(time_ns)
        st_id = station_id or (details.get("station_id") if details else None)
        op_id = operation_id or (details.get("operation_id") if details else None)
        unit.record_transition(
            time_ns=time_ns,
            state=state,
            location=location,
            station_id=st_id,
            operation_id=op_id,
        )
        audit_details: dict[str, Any] = {
            "transition": state.value,
            "location": location,
            "quality_state": unit.quality_state,
        }
        if details:
            audit_details.update(details)
        if st_id and "station_id" not in audit_details:
            audit_details["station_id"] = st_id
        if op_id and "operation_id" not in audit_details:
            audit_details["operation_id"] = op_id
        self.audit_logger.record(
            event_type="unit_lifecycle",
            simulated_time_ns=time_ns,
            episode_id=self.episode_id,
            branch_id=getattr(self.decision_coordinator, "branch_id", None),
            entity_ids=[unit.id, location],
            details=audit_details,
        )

    def _record_operation_started(
        self,
        unit_id: str,
        station_id: str,
        op_id: str,
        time_ns: int,
    ) -> None:
        self._record_domain_progress(time_ns)
        unit = self.units.get(unit_id)
        quality_state = unit.quality_state if unit else "unknown"
        self.audit_logger.record(
            event_type="unit_lifecycle",
            simulated_time_ns=time_ns,
            episode_id=self.episode_id,
            branch_id=getattr(self.decision_coordinator, "branch_id", None),
            entity_ids=[unit_id, station_id],
            details={
                "transition": "operation_started",
                "operation_id": op_id,
                "station_id": station_id,
                "quality_state": quality_state,
            },
        )

    def _record_operation_completed(
        self,
        unit_id: str,
        station_id: str,
        op_id: str,
        time_ns: int,
    ) -> None:
        self._record_domain_progress(time_ns)
        unit = self.units.get(unit_id)
        quality_state = unit.quality_state if unit else "unknown"
        self.audit_logger.record(
            event_type="unit_lifecycle",
            simulated_time_ns=time_ns,
            episode_id=self.episode_id,
            branch_id=getattr(self.decision_coordinator, "branch_id", None),
            entity_ids=[unit_id, station_id],
            details={
                "transition": "operation_completed",
                "operation_id": op_id,
                "station_id": station_id,
                "quality_state": quality_state,
            },
        )

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
    def reserved_route_occupancy(self) -> dict[str, int]:
        return self.domain.reserved_route_occupancy

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
        self.kernel.register_handler("SAFE_POINT_TRIGGER", self._handle_safe_point_trigger)
        self.kernel.register_handler("COMPLETE_RECONFIGURATION", self._handle_complete_reconfiguration)

        self.kernel.register_handler("TELEMETRY_INTERVAL", self._handle_telemetry_interval)
        self.kernel.register_handler("DEADLOCK_CHECK", self._handle_deadlock_check)

        if self.max_interval_without_progress_ns is not None:
            self.kernel.schedule(
                time_ns=self.cfg.episode.start_time_ns + self.max_interval_without_progress_ns,
                priority=EventPriority.SAFETY,
                event_type="DEADLOCK_CHECK",
            )

        for t in self.cfg.decision_triggers:
            if isinstance(t, SafePointTriggerConfig):
                for time_val in t.times_ns:
                    self.kernel.schedule(
                        time_ns=time_val,
                        priority=EventPriority.RESOURCE,
                        event_type="SAFE_POINT_TRIGGER",
                        payload={"trigger_id": t.id, "target_id": t.target_id},
                    )
                if t.interval_ns and t.interval_ns > 0:
                    self.kernel.schedule(
                        time_ns=t.interval_ns,
                        priority=EventPriority.RESOURCE,
                        event_type="SAFE_POINT_TRIGGER",
                        payload={"trigger_id": t.id, "target_id": t.target_id, "interval_ns": t.interval_ns},
                    )

        if (
            self.cfg.telemetry
            and self.cfg.telemetry.enabled
            and self.cfg.telemetry.sample_interval_ns
            and self.cfg.telemetry.sample_interval_ns > 0
        ):
            self.kernel.schedule(
                time_ns=self.cfg.episode.start_time_ns + self.cfg.telemetry.sample_interval_ns,
                priority=EventPriority.TELEMETRY,
                event_type="TELEMETRY_INTERVAL",
                payload={"interval_ns": self.cfg.telemetry.sample_interval_ns},
            )

    def _handle_telemetry_interval(self, k: EventKernel, event: ScheduledEvent) -> None:
        self._sample_telemetry(sample_type="interval")
        interval_ns = event.payload.get("interval_ns")
        if interval_ns and interval_ns > 0:
            next_t = k.current_time_ns + interval_ns
            max_t = self.cfg.episode.end_condition.max_time_ns
            if max_t is None or next_t <= max_t:
                k.schedule(
                    time_ns=next_t,
                    priority=EventPriority.TELEMETRY,
                    event_type="TELEMETRY_INTERVAL",
                    payload={"interval_ns": interval_ns},
                )

    def _handle_deadlock_check(self, k: EventKernel, event: ScheduledEvent) -> None:
        if self.is_deadlocked or self.is_aborted or self._is_terminal_condition_met(k):
            return
        if self.max_interval_without_progress_ns is None:
            return

        elapsed = k.current_time_ns - self.last_domain_progress_time_ns
        if elapsed >= self.max_interval_without_progress_ns:
            diagnosis = analyze_deadlock(self)
            if diagnosis is not None:
                self._terminate_with_deadlock(diagnosis)
                return
            else:
                k.schedule(
                    time_ns=k.current_time_ns + self.max_interval_without_progress_ns,
                    priority=EventPriority.SAFETY,
                    event_type="DEADLOCK_CHECK",
                )
        else:
            next_t = self.last_domain_progress_time_ns + self.max_interval_without_progress_ns
            if next_t > k.current_time_ns:
                k.schedule(
                    time_ns=next_t,
                    priority=EventPriority.SAFETY,
                    event_type="DEADLOCK_CHECK",
                )

    def _emit_domain_event(self, event_name: str) -> None:
        if not self.is_telemetry_enabled or not self.cfg.telemetry:
            return
        domain_events = self.cfg.telemetry.domain_events
        if "all" in domain_events or event_name in domain_events:
            self._sample_telemetry(sample_type="domain_event", event_name=event_name)

    def _compute_current_metrics(self) -> dict[str, Any]:
        warm_up_time_ns = self.cfg.episode.warm_up_time_ns or 0
        good_completed = [
            u
            for u in self.units.values()
            if u.state == ProductionUnitState.TERMINAL
            and u.location != "scrapped"
            and u.quality_state != "scrapped"
            and (not u.history or u.history[-1].time_ns >= warm_up_time_ns)
            and u.history
        ]
        good_output = len(good_completed)
        scrap = sum(
            1
            for u in self.units.values()
            if u.state == ProductionUnitState.TERMINAL
            and (u.location == "scrapped" or u.quality_state == "scrapped")
            and (not u.history or u.history[-1].time_ns >= warm_up_time_ns)
        )
        wip = sum(
            1
            for u in self.units.values()
            if u.state not in (ProductionUnitState.CREATED, ProductionUnitState.TERMINAL)
        )
        if good_completed:
            lead_time_ns = int(
                round(
                    sum(u.history[-1].time_ns - u.history[0].time_ns for u in good_completed)
                    / len(good_completed)
                )
            )
            lateness_ns = sum(
                max(0, u.history[-1].time_ns - u.due_date_ns)
                for u in good_completed
                if u.due_date_ns is not None
            )
        else:
            lead_time_ns = 0
            lateness_ns = 0

        downtime_ns = sum(
            m.total_failed_time_ns + m.total_maintenance_time_ns for m in self.machines.values()
        )
        return {
            "good_output": good_output,
            "scrap": scrap,
            "wip": wip,
            "lead_time_ns": lead_time_ns,
            "downtime_ns": downtime_ns,
            "lateness_ns": lateness_ns,
            "resource_utilization": {
                "machines": {m.id: m.utilization for m in self.machines.values()},
                "workers": {w.id: w.utilization for w in self.workers.values()},
                "vehicles": {v.id: v.utilization for v in self.vehicles.values()},
            },
            "total_strategic_cost": self.total_strategic_cost,
        }

    def _sample_telemetry(self, sample_type: str = "interval", event_name: str | None = None) -> None:
        if not self.is_telemetry_enabled:
            return

        raw_metrics = self._compute_current_metrics()
        machines_busy = sum(1 for m in self.machines.values() if len(m.active_allocations) > 0)
        machines_idle = sum(
            1
            for m in self.machines.values()
            if not m.is_failed and not m.is_in_maintenance and len(m.active_allocations) == 0
        )
        machines_failed = sum(1 for m in self.machines.values() if m.is_failed)
        workers_busy = sum(1 for w in self.workers.values() if len(w.active_allocations) > 0)
        workers_idle = sum(
            1 for w in self.workers.values() if len(w.active_allocations) == 0
        )
        vehicles_busy = sum(
            1 for v in self.vehicles.values() if v.current_order_id is not None
        )
        vehicles_idle = sum(
            1 for v in self.vehicles.values() if v.current_order_id is None
        )

        current_reward = None
        if self.cfg.reward_policy:
            current_reward, _ = _compute_reward(raw_metrics, self.cfg.reward_policy)

        sample = {
            "simulated_time_ns": self.kernel.current_time_ns,
            "sample_type": sample_type,
            "event_name": event_name,
            "good_output": raw_metrics["good_output"],
            "scrap": raw_metrics["scrap"],
            "wip": raw_metrics["wip"],
            "lead_time_ns": raw_metrics["lead_time_ns"],
            "downtime_ns": raw_metrics["downtime_ns"],
            "lateness_ns": raw_metrics["lateness_ns"],
            "machines_busy": machines_busy,
            "machines_idle": machines_idle,
            "machines_failed": machines_failed,
            "workers_busy": workers_busy,
            "workers_idle": workers_idle,
            "vehicles_busy": vehicles_busy,
            "vehicles_idle": vehicles_idle,
            "current_reward": current_reward,
        }
        self.telemetry_manager.record_metrics_sample(sample)

    def _build_buffer_observation(self, buffer_id: str, time_ns: int) -> BufferObservation:
        buf = self.buffers[buffer_id]
        occupants: list[BufferOccupantSummary] = []
        for uid in buf.occupants:
            unit = self.units[uid]
            enter_t: int | None = None
            for rec in reversed(unit.history):
                if rec.location == buffer_id and rec.state == ProductionUnitState.IN_BUFFER:
                    enter_t = rec.time_ns
                    break
            occupants.append(
                BufferOccupantSummary(
                    unit_id=uid,
                    variant=unit.variant,
                    due_date_ns=unit.due_date_ns,
                    enter_time_ns=enter_t,
                    findings_count=len(unit.findings),
                )
            )

        upstream_nodes = [r.source_node_id for r in self.routes_to.get(buffer_id, [])]
        downstream_nodes = [r.target_node_id for r in self.routes_from.get(buffer_id, [])]

        route_statuses: dict[str, Any] = {}
        for r in self.routes_from.get(buffer_id, []):
            route_statuses[r.id] = {
                "target_node_id": r.target_node_id,
                "capacity": r.capacity,
                "active_occupancy": self.active_route_occupancy.get(r.id, 0),
                "reserved_occupancy": self.reserved_route_occupancy.get(r.id, 0),
            }

        completed_count = sum(
            1 for u in self.units.values() if u.state == ProductionUnitState.TERMINAL and u.location == "sink"
        )
        scrapped_count = sum(
            1 for u in self.units.values() if u.state == ProductionUnitState.TERMINAL and u.location == "scrapped"
        )
        wip_count = sum(
            1
            for u in self.units.values()
            if u.state not in (ProductionUnitState.CREATED, ProductionUnitState.TERMINAL)
        )
        rework_count = sum(1 for u in self.units.values() if u.is_in_rework)

        history_records = list(self.buffer_history.get(buffer_id, []))[-10:]

        return BufferObservation(
            schema_version="1.0",
            buffer_id=buffer_id,
            capacity=buf.capacity,
            occupancy=len(buf.occupants),
            occupants=occupants,
            upstream_nodes=sorted(set(upstream_nodes)),
            downstream_nodes=sorted(set(downstream_nodes)),
            route_statuses=route_statuses,
            aggregate_metrics={
                "simulation_time_ns": time_ns,
                "completed_units": completed_count,
                "scrapped_units": scrapped_count,
                "wip": wip_count,
                "rework_count": rework_count,
            },
            history=history_records,
        )

    def _evaluate_buffer_triggers(
        self,
        buffer_id: str,
        old_occupancy: int,
        new_occupancy: int,
        time_ns: int,
    ) -> None:
        triggers = self.decision_triggers.get(buffer_id, [])
        for trig in triggers:
            if trig.check_transition(buffer_id, old_occupancy, new_occupancy, time_ns):
                obs = self._build_buffer_observation(buffer_id, time_ns)
                req_id = f"req-{buffer_id}-{trig.config.id}-{time_ns}"
                req = DecisionRequest(
                    request_id=req_id,
                    request_type="buffer_threshold",
                    time_ns=time_ns,
                    target_id=buffer_id,
                    trigger_id=trig.config.id,
                    observation=obs,
                    action_schema="buffer_reorder",
                )
                self.decision_coordinator.add_request(req)

    def _build_machine_observation(self, machine_id: str, time_ns: int) -> MachineObservation:
        mach = self.machines[machine_id]
        policy_summary = dict(mach.maintenance_policy) if mach.maintenance_policy else {}
        return MachineObservation(
            schema_version="1.0",
            machine_id=machine_id,
            health=mach.health,
            operating_mode=mach.operating_mode,
            available_modes=["nominal", "eco", "boost", "maintenance"],
            is_in_maintenance=mach.is_in_maintenance,
            is_failed=mach.is_failed,
            physical_state={"health": mach.health},
            maintenance_policy_summary=policy_summary,
            aggregate_metrics={
                "simulation_time_ns": time_ns,
                "operations_completed": mach.operations_completed,
                "total_busy_time_ns": mach.total_busy_time_ns,
                "total_maintenance_time_ns": mach.total_maintenance_time_ns,
                "failure_count": mach.failure_count,
            },
        )

    def _build_strategic_observation(self, target_id: str, time_ns: int) -> StrategicObservation:
        bounds: QualityControlBounds | None = None
        for t in self.cfg.decision_triggers:
            if isinstance(t, SafePointTriggerConfig) and t.target_id == target_id:
                if t.quality_bounds is not None:
                    bounds = QualityControlBounds(
                        min_inspection_intensity=t.quality_bounds.min_inspection_intensity,
                        max_inspection_intensity=t.quality_bounds.max_inspection_intensity,
                        min_sampling_rate=t.quality_bounds.min_sampling_rate,
                        max_sampling_rate=t.quality_bounds.max_sampling_rate,
                        min_release_threshold=t.quality_bounds.min_release_threshold,
                        max_release_threshold=t.quality_bounds.max_release_threshold,
                    )
        avail_workers = [
            w.id for w in self.workers.values() if w.is_available(time_ns)
        ]
        is_safe = True
        if target_id in self.stations:
            st = self.stations[target_id]
            if st.is_busy:
                is_safe = False
        return StrategicObservation(
            schema_version="1.0",
            target_id=target_id,
            is_safe_point=is_safe,
            allowed_actions=["reconfiguration", "worker_reassignment", "quality_control"],
            current_configuration={},
            quality_control_bounds=bounds,
            available_workers=avail_workers,
            aggregate_metrics={"simulation_time_ns": time_ns},
        )

    def _build_route_summary(self, route: RouteConfig) -> RouteSummaryObservation:
        cur_occ = self.active_route_occupancy.get(route.id, 0) + self.reserved_route_occupancy.get(route.id, 0)
        is_adm = self._can_accept(route.target_node_id)
        if route.capacity is not None and cur_occ >= route.capacity:
            is_adm = False
        return RouteSummaryObservation(
            route_id=route.id,
            source_node_id=route.source_node_id,
            target_node_id=route.target_node_id,
            capacity=route.capacity,
            current_occupancy=cur_occ,
            transit_time_ns=route.transit_time_ns,
            is_admissible=is_adm,
        )

    def _build_routing_observation(
        self, node_id: str, time_ns: int, unit_id: str | None = None
    ) -> RoutingObservation:
        target_unit_id = unit_id
        if target_unit_id is None:
            if node_id in self.buffers and self.buffers[node_id].occupants:
                target_unit_id = self.buffers[node_id].occupants[0]
            elif node_id in self.source_pending_units and self.source_pending_units[node_id]:
                target_unit_id = self.source_pending_units[node_id][0]

        unit = self.units.get(target_unit_id) if target_unit_id else None
        variant = unit.variant if unit else "standard"
        due_date_ns = unit.due_date_ns if unit else None
        findings_count = len(unit.findings) if unit else 0

        c_routes = [self._build_route_summary(r) for r in self.routes_from.get(node_id, [])]

        return RoutingObservation(
            schema_version="1.0",
            unit_id=target_unit_id or "",
            variant=variant,
            current_node_id=node_id,
            due_date_ns=due_date_ns,
            findings_count=findings_count,
            candidate_routes=c_routes,
            aggregate_metrics={"simulation_time_ns": time_ns},
        )

    def _build_dispatch_observation(
        self, time_ns: int, order_id: str | None = None
    ) -> DispatchObservation:
        target_order_id = order_id
        if target_order_id is None and self.pending_transport_orders:
            target_order_id = self.pending_transport_orders[0]

        order = self.transport_orders.get(target_order_id) if target_order_id else None
        unit_id = order.unit_id if order else ""
        unit = self.units.get(unit_id)
        variant = unit.variant if unit else "standard"
        source_node_id = order.source_node_id if order else ""
        target_node_id = order.target_node_id if order else ""
        created_time_ns = order.created_time_ns if order else time_ns
        due_date_ns = unit.due_date_ns if unit else None
        findings_count = len(unit.findings) if unit else 0

        c_routes = [self._build_route_summary(r) for r in self.routes_from.get(source_node_id, [])]

        avail_vehs: list[VehicleSummaryObservation] = []
        for v in self.vehicles.values():
            if v.is_available():
                dist = self._compute_node_distance(v.location, source_node_id) or 0
                avail_vehs.append(
                    VehicleSummaryObservation(
                        vehicle_id=v.id,
                        location=v.location,
                        distance_to_pickup_ns=dist,
                        speed_multiplier=v.speed_multiplier,
                    )
                )

        return DispatchObservation(
            schema_version="1.0",
            order_id=target_order_id or "",
            unit_id=unit_id,
            variant=variant,
            source_node_id=source_node_id,
            target_node_id=target_node_id,
            created_time_ns=created_time_ns,
            due_date_ns=due_date_ns,
            findings_count=findings_count,
            candidate_routes=c_routes,
            available_vehicles=avail_vehs,
            aggregate_metrics={"simulation_time_ns": time_ns},
        )

    def _build_observation_for_request(self, req_or_target: Any, time_ns: int) -> Any:
        if isinstance(req_or_target, DecisionRequest):
            req_type = req_or_target.request_type
            target_id = req_or_target.target_id
        else:
            req_type = "buffer_threshold"
            target_id = str(req_or_target)

        if req_type == "buffer_threshold" or target_id in self.buffers:
            return self._build_buffer_observation(target_id, time_ns)
        elif req_type == "machine" or target_id in self.machines:
            return self._build_machine_observation(target_id, time_ns)
        elif req_type == "strategic":
            return self._build_strategic_observation(target_id, time_ns)
        elif req_type == "routing":
            return self._build_routing_observation(target_id, time_ns)
        elif req_type == "dispatch":
            return self._build_dispatch_observation(time_ns)
        else:
            if target_id in self.buffers:
                return self._build_buffer_observation(target_id, time_ns)
            return self._build_strategic_observation(target_id, time_ns)

    def _process_decision_batch(self) -> None:
        batch = self.decision_coordinator.form_batch(
            time_ns=self.kernel.current_time_ns,
            observation_builder=lambda req: self._build_observation_for_request(req, self.kernel.current_time_ns),
        )
        if batch is None:
            return

        for req in batch.requests:
            self.audit_logger.record(
                event_type="decision_request",
                simulated_time_ns=self.kernel.current_time_ns,
                episode_id=batch.episode_id,
                branch_id=batch.branch_id,
                batch_id=batch.batch_id,
                entity_ids=[req.target_id],
                details={
                    "request_id": req.request_id,
                    "request_type": req.request_type,
                    "target_id": req.target_id,
                    "trigger_id": req.trigger_id,
                    "action_schema": req.action_schema,
                },
            )

        response: DecisionBatchResponse | None = None
        diagnostics: list[DecisionDiagnosticRecord] = []

        if self.decision_provider is not None:
            try:
                response = self.decision_provider.decide(batch)
                if response is not None:
                    is_valid, validation_diags = validate_decision_batch_response(batch, response)
                    diagnostics.extend(validation_diags)
                else:
                    diagnostics.append(
                        DecisionDiagnosticRecord(
                            code="NULL_RESPONSE",
                            message="Decision provider returned None",
                            batch_id=batch.batch_id,
                        )
                    )
            except Exception as exc:
                diagnostics.append(
                    DecisionDiagnosticRecord(
                        code="PROVIDER_EXCEPTION",
                        message=f"Decision provider raised exception: {exc}",
                        batch_id=batch.batch_id,
                    )
                )
        else:
            diagnostics.append(
                DecisionDiagnosticRecord(
                    code="NO_PROVIDER",
                    message="No decision provider configured",
                    batch_id=batch.batch_id,
                )
            )

        if response is not None:
            for action in response.actions:
                target_id = (
                    getattr(action, "buffer_id", None)
                    or getattr(action, "target_id", None)
                    or getattr(action, "machine_id", None)
                    or getattr(action, "node_id", None)
                    or getattr(action, "unit_id", None)
                )
                entity_ids = [target_id] if target_id else []
                self.audit_logger.record(
                    event_type="decision_action",
                    simulated_time_ns=self.kernel.current_time_ns,
                    episode_id=batch.episode_id,
                    branch_id=batch.branch_id,
                    batch_id=batch.batch_id,
                    entity_ids=entity_ids,
                    provenance=response.provenance.model_dump(mode="json") if response.provenance else None,
                    details={
                        "action_type": action.action_type,
                        "action": action.model_dump(mode="json"),
                    },
                )

        is_valid_resp = (response is not None and len(diagnostics) == 0)
        self.audit_logger.record(
            event_type="validation_outcome",
            simulated_time_ns=self.kernel.current_time_ns,
            episode_id=batch.episode_id,
            branch_id=batch.branch_id,
            batch_id=batch.batch_id,
            details={
                "is_valid": is_valid_resp,
                "diagnostics": [d.model_dump(mode="json") for d in diagnostics],
            },
        )

        if is_valid_resp and response is not None:
            self._apply_decision_actions(batch, response)
        else:
            self._handle_decision_failure(batch, diagnostics)

        self.audit_logger.record(
            event_type="reward",
            simulated_time_ns=self.kernel.current_time_ns,
            episode_id=batch.episode_id,
            branch_id=batch.branch_id,
            batch_id=batch.batch_id,
            details={
                "batch_id": batch.batch_id,
                "total_strategic_cost": self.total_strategic_cost,
                "events_processed": self.kernel.events_processed,
            },
        )

    def _apply_actions_list(
        self, batch: DecisionBatch, actions: Sequence[DecisionAction]
    ) -> None:
        for action in actions:
            if isinstance(action, BufferReorderAction):
                buf = self.buffers.get(action.target_id)
                if buf is not None:
                    buf.occupants = list(action.new_order)
                self._try_pull_upstream(self.kernel, action.target_id)
                for r in self.routes_from.get(action.target_id, []):
                    self._try_pull_upstream(self.kernel, r.target_node_id)
            elif isinstance(action, MachineModeAction):
                mach = self.machines.get(action.target_id)
                if mach is not None:
                    mach.operating_mode = action.mode
            elif isinstance(action, MaintenanceAction):
                if action.trigger_maintenance:
                    mach = self.machines.get(action.target_id)
                    if mach is not None:
                        self._trigger_maintenance(self.kernel, mach)
            elif isinstance(action, ReconfigurationAction):
                if action.cost > 0:
                    self.total_strategic_cost += action.cost
                st = self.stations.get(action.target_id)
                if st is not None and action.duration_ns > 0:
                    st.start_reconfiguration(action.configuration, self.kernel.current_time_ns)
                    self.kernel.schedule(
                        time_ns=self.kernel.current_time_ns + action.duration_ns,
                        priority=EventPriority.COMPLETION,
                        event_type="COMPLETE_RECONFIGURATION",
                        payload={"station_id": action.target_id},
                    )
            elif isinstance(action, WorkerReassignmentAction):
                if action.cost > 0:
                    self.total_strategic_cost += action.cost
            elif isinstance(action, QualityControlAction):
                if action.cost > 0:
                    self.total_strategic_cost += action.cost
                st = self.stations.get(action.target_id)
                if st is not None:
                    for op in st.operations.values():
                        if op.inspection is not None:
                            if action.inspection_intensity is not None:
                                op.inspection["sensitivity"] = action.inspection_intensity
                            if action.sampling_rate is not None:
                                op.inspection["sampling_rate"] = action.sampling_rate
                            if action.release_threshold is not None:
                                op.inspection["release_threshold"] = action.release_threshold
            elif isinstance(action, RoutingAction):
                pass
            elif isinstance(action, DispatchAction):
                pass

        for req in batch.requests:
            if req.target_id in self.buffers:
                self._try_pull_upstream(self.kernel, req.target_id)
                for r in self.routes_from.get(req.target_id, []):
                    self._try_pull_upstream(self.kernel, r.target_node_id)
        self._try_dispatch_pending_orders(self.kernel)

    def _apply_decision_actions(
        self, batch: DecisionBatch, response: DecisionBatchResponse
    ) -> None:
        self._apply_actions_list(batch, response.actions)

        self.decision_batches.append(
            {
                "batch_id": batch.batch_id,
                "time_ns": batch.time_ns,
                "status": "applied",
                "provenance": response.provenance.model_dump(),
                "actions": [a.model_dump() for a in response.actions],
            }
        )

        current_reward = None
        if self.cfg.reward_policy:
            current_reward, _ = _compute_reward(self._compute_current_metrics(), self.cfg.reward_policy)

        for req in batch.requests:
            matching_act = next(
                (a for a in response.actions if getattr(a, "target_id", None) == req.target_id),
                response.actions[0] if response.actions else None,
            )
            self.telemetry_manager.record_training_record(
                {
                    "simulated_time_ns": self.kernel.current_time_ns,
                    "batch_id": batch.batch_id,
                    "request_id": req.request_id,
                    "request_type": req.request_type,
                    "target_id": req.target_id,
                    "action_type": matching_act.action_type if matching_act else None,
                    "action_payload_json": json.dumps(matching_act.model_dump()) if matching_act else None,
                    "provider_id": response.provenance.provider_id,
                    "reward": current_reward,
                    "is_terminal": self._is_terminal_condition_met(self.kernel),
                }
            )
        self._emit_domain_event("decision_batch")

    def _handle_safe_point_trigger(self, k: EventKernel, event: ScheduledEvent) -> None:
        target_id = event.payload.get("target_id", "")
        trigger_id = event.payload.get("trigger_id", "")
        interval_ns = event.payload.get("interval_ns")
        st = self.stations.get(target_id)
        is_safe = True
        if st is not None and st.is_busy:
            is_safe = False
        obs = self._build_strategic_observation(target_id, k.current_time_ns)
        req = DecisionRequest(
            request_id=f"req-strat-{target_id}-{k.current_time_ns}",
            request_type="strategic",
            time_ns=k.current_time_ns,
            target_id=target_id,
            trigger_id=trigger_id,
            observation=obs,
            action_schema="strategic",
            is_safe_point=is_safe,
        )
        self.decision_coordinator.add_request(req)
        if interval_ns and interval_ns > 0:
            k.schedule(
                time_ns=k.current_time_ns + interval_ns,
                priority=EventPriority.RESOURCE,
                event_type="SAFE_POINT_TRIGGER",
                payload={"trigger_id": trigger_id, "target_id": target_id, "interval_ns": interval_ns},
            )

    def _handle_complete_reconfiguration(self, k: EventKernel, event: ScheduledEvent) -> None:
        station_id = event.payload.get("station_id", "")
        st = self.stations.get(station_id)
        if st is not None:
            st.complete_reconfiguration(k.current_time_ns)
            self._try_pull_upstream(k, station_id)
            for r in self.routes_from.get(station_id, []):
                self._try_pull_upstream(k, r.target_node_id)
            self._try_dispatch_pending_orders(k)

    def _handle_decision_failure(
        self,
        batch: DecisionBatch,
        diagnostics: list[DecisionDiagnosticRecord],
    ) -> None:
        self.decision_diagnostics.extend([d.model_dump() for d in diagnostics])

        should_abort = False
        abort_trigger_id = None
        fallback_policy_name = "fifo"

        for req in batch.requests:
            matched_trig = None
            if req.trigger_id:
                for trig in self.decision_triggers.get(req.target_id, []):
                    if trig.config.id == req.trigger_id:
                        matched_trig = trig
                        break
            if matched_trig is None:
                trigs = self.decision_triggers.get(req.target_id, [])
                if trigs:
                    matched_trig = trigs[0]

            if matched_trig is not None:
                if matched_trig.config.on_failure == "abort":
                    should_abort = True
                    abort_trigger_id = matched_trig.config.id
                    break
                fallback_policy_name = matched_trig.config.fallback_policy

        if should_abort:
            self.is_aborted = True
            reasons = "; ".join(d.message for d in diagnostics)
            self.abort_reason = (
                f"Trigger '{abort_trigger_id}' aborted episode due to decision failure: {reasons}"
            )
            self.audit_logger.record(
                event_type="failure",
                simulated_time_ns=self.kernel.current_time_ns,
                episode_id=batch.episode_id,
                branch_id=batch.branch_id,
                batch_id=batch.batch_id,
                details={
                    "failure_type": "decision_abort",
                    "abort_trigger_id": abort_trigger_id,
                    "abort_reason": self.abort_reason,
                },
            )
            self.decision_batches.append(
                {
                    "batch_id": batch.batch_id,
                    "time_ns": batch.time_ns,
                    "status": "aborted",
                    "diagnostics": [d.model_dump() for d in diagnostics],
                }
            )
            return

        if fallback_policy_name in ("fifo", "baseline"):
            fallback_policy = BaselineFallbackPolicy()
        else:
            raise ValueError(f"Unsupported fallback policy: '{fallback_policy_name}'")

        fallback_actions = fallback_policy.generate_fallback_actions(batch)
        self.audit_logger.record(
            event_type="fallback",
            simulated_time_ns=self.kernel.current_time_ns,
            episode_id=batch.episode_id,
            branch_id=batch.branch_id,
            batch_id=batch.batch_id,
            details={
                "reason": "; ".join(d.message for d in diagnostics),
                "fallback_policy": fallback_policy_name,
                "fallback_actions": [a.model_dump(mode="json") for a in fallback_actions],
            },
        )
        for f_action in fallback_actions:
            target_id = (
                getattr(f_action, "buffer_id", None)
                or getattr(f_action, "target_id", None)
                or getattr(f_action, "machine_id", None)
                or getattr(f_action, "node_id", None)
                or getattr(f_action, "unit_id", None)
            )
            entity_ids = [target_id] if target_id else []
            self.audit_logger.record(
                event_type="decision_action",
                simulated_time_ns=self.kernel.current_time_ns,
                episode_id=batch.episode_id,
                branch_id=batch.branch_id,
                batch_id=batch.batch_id,
                entity_ids=entity_ids,
                provenance={"provider_id": f"fallback-{fallback_policy_name}"},
                details={
                    "action_type": f_action.action_type,
                    "action": f_action.model_dump(mode="json"),
                },
            )

        self._apply_actions_list(batch, fallback_actions)

        self.decision_batches.append(
            {
                "batch_id": batch.batch_id,
                "time_ns": batch.time_ns,
                "status": "fallback",
                "diagnostics": [d.model_dump() for d in diagnostics],
                "actions": [a.model_dump() for a in fallback_actions],
            }
        )

        current_reward = None
        if self.cfg.reward_policy:
            current_reward, _ = _compute_reward(self._compute_current_metrics(), self.cfg.reward_policy)

        for req in batch.requests:
            matching_act = next(
                (a for a in fallback_actions if getattr(a, "target_id", None) == req.target_id),
                fallback_actions[0] if fallback_actions else None,
            )
            self.telemetry_manager.record_training_record(
                {
                    "simulated_time_ns": self.kernel.current_time_ns,
                    "batch_id": batch.batch_id,
                    "request_id": req.request_id,
                    "request_type": req.request_type,
                    "target_id": req.target_id,
                    "action_type": matching_act.action_type if matching_act else None,
                    "action_payload_json": json.dumps(matching_act.model_dump()) if matching_act else None,
                    "provider_id": f"fallback-{fallback_policy_name}",
                    "reward": current_reward,
                    "is_terminal": self._is_terminal_condition_met(self.kernel),
                }
            )
        self._emit_domain_event("decision_batch")

    def _can_accept(self, node_id: str) -> bool:
        if any(req.target_id == node_id for req in self.decision_coordinator.pending_requests):
            return False
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
            if any(req.target_id == node_id for req in self.decision_coordinator.pending_requests):
                return False
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

        self.pending_transport_orders.sort(
            key=lambda oid: (
                self.transport_orders[oid].created_time_ns,
                (
                    (0, self.units[self.transport_orders[oid].unit_id].due_date_ns)
                    if self.units[self.transport_orders[oid].unit_id].due_date_ns is not None
                    else (1, 0)
                ),
                oid,
            )
        )

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

            ctx = DispatchContext(
                order=order,
                candidate_routes=candidates,
                available_vehicles=available_vehicles,
                active_route_occupancy=self.active_route_occupancy,
                node_distance_fn=self._compute_node_distance,
                can_accept_fn=self._can_accept,
                reserved_route_occupancy=self.reserved_route_occupancy,
                unconstrained=unconstrained,
            )
            decision = self.dispatch_policy.select_dispatch(ctx)

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
                self.reserved_route_occupancy[route.id] = (
                    self.reserved_route_occupancy.get(route.id, 0) + 1
                )
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
        if self.reserved_route_occupancy.get(route.id, 0) > 0:
            self.reserved_route_occupancy[route.id] -= 1
        self.active_route_occupancy[route.id] = (
            self.active_route_occupancy.get(route.id, 0) + 1
        )

        unit = self.units[order.unit_id]
        self._remove_unit_from_node(order.source_node_id, unit.id, k.current_time_ns)
        order.pickup(k.current_time_ns)
        self._record_unit_transition(
            unit,
            state=ProductionUnitState.IN_TRANSPORT,
            location=route.id,
            time_ns=k.current_time_ns,
            details={"route_id": route.id, "vehicle_id": vehicle.id if vehicle else None},
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
            old_occ = len(buf.occupants)
            if buf.occupants and buf.occupants[0] == unit_id:
                buf.pop_unit()
            elif unit_id in buf.occupants:
                buf.occupants.remove(unit_id)
            new_occ = len(buf.occupants)
            self.buffer_history.setdefault(node_id, []).append(
                {
                    "time_ns": time_ns,
                    "event": "departed",
                    "unit_id": unit_id,
                    "occupancy": new_occ,
                }
            )
            self._evaluate_buffer_triggers(node_id, old_occ, new_occ, time_ns)
        elif kind == "station":
            st = self.stations[node_id]
            if st.has_output_units() and st.output_buffer[0] == unit_id:
                st.pop_output_unit()
                if st.is_blocked:
                    blocked_uid = st.blocked_unit_id
                    assert blocked_uid is not None
                    st.end_blocking(time_ns)
                    st.enqueue_output_unit(blocked_uid)
                    self._record_unit_transition(
                        self.units[blocked_uid],
                        state=ProductionUnitState.IN_STATION,
                        location=node_id,
                        time_ns=time_ns,
                        details={"station_id": node_id},
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
        self._record_unit_transition(
            unit,
            state=ProductionUnitState.RELEASED,
            location=source_id,
            time_ns=k.current_time_ns,
        )
        self.source_pending_units[source_id].append(unit_id)
        self._create_transport_order(unit_id, source_id, k.current_time_ns)
        self._try_dispatch_pending_orders(k)

    def _handle_sink_arrival(self, k: EventKernel, unit_id: str, node_id: str) -> None:
        self._record_unit_transition(
            self.units[unit_id],
            state=ProductionUnitState.TERMINAL,
            location="terminal",
            time_ns=k.current_time_ns,
            details={"sink_id": node_id},
        )
        self._emit_domain_event("sink_arrival")
        self._try_pull_upstream(k, node_id)

    def _handle_buffer_arrival(self, k: EventKernel, unit_id: str, node_id: str) -> None:
        buf = self.buffers[node_id]
        old_occ = len(buf.occupants)
        buf.add_unit(unit_id)
        new_occ = len(buf.occupants)
        self._record_unit_transition(
            self.units[unit_id],
            state=ProductionUnitState.IN_BUFFER,
            location=node_id,
            time_ns=k.current_time_ns,
            details={"buffer_id": node_id, "occupancy": new_occ},
        )
        self.buffer_history.setdefault(node_id, []).append(
            {
                "time_ns": k.current_time_ns,
                "event": "entered",
                "unit_id": unit_id,
                "occupancy": new_occ,
            }
        )
        self._evaluate_buffer_triggers(node_id, old_occ, new_occ, k.current_time_ns)
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
                self._record_operation_started(unit_id, station_id, op.id, time_ns)
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
            self._record_unit_transition(
                u,
                state=ProductionUnitState.TERMINAL,
                location="terminal",
                time_ns=time_ns,
                details={"reason": "interrupted_scrap", "station_id": station_id},
            )
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
        self.audit_logger.record(
            event_type="failure",
            simulated_time_ns=k.current_time_ns,
            episode_id=self.episode_id,
            branch_id=getattr(self.decision_coordinator, "branch_id", None),
            entity_ids=[mach_id],
            details={"failure_type": "disruption", "machine_id": mach_id, "duration_ns": dur_ns},
        )
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
        self.audit_logger.record(
            event_type="failure",
            simulated_time_ns=k.current_time_ns,
            episode_id=self.episode_id,
            branch_id=getattr(self.decision_coordinator, "branch_id", None),
            entity_ids=[mach_id],
            details={"failure_type": "machine_failure", "machine_id": mach_id, "health": mach.health},
        )
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

        self._record_unit_transition(
            self.units[unit_id],
            state=ProductionUnitState.IN_STATION,
            location=node_id,
            time_ns=k.current_time_ns,
            details={"station_id": node_id, "operation_id": op.id},
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
            self._record_operation_started(unit_id, node_id, op.id, k.current_time_ns)
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
            self._record_unit_transition(
                unit,
                state=ProductionUnitState.IN_STATION,
                location=station_id,
                time_ns=k.current_time_ns,
                details={"station_id": station_id, "sub_state": "output_queue"},
            )
        else:
            st.start_blocking(unit_id, k.current_time_ns)
            self._record_unit_transition(
                unit,
                state=ProductionUnitState.BLOCKED,
                location=station_id,
                time_ns=k.current_time_ns,
                details={"station_id": station_id},
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
        self._record_operation_completed(unit_id, station_id, current_op.id, k.current_time_ns)
        self._emit_domain_event("operation_completed")

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
            self.audit_logger.record(
                event_type="unit_lifecycle",
                simulated_time_ns=k.current_time_ns,
                episode_id=self.episode_id,
                branch_id=getattr(self.decision_coordinator, "branch_id", None),
                entity_ids=[unit.id, station_id],
                details={
                    "transition": "quality_inspected",
                    "station_id": station_id,
                    "operation_id": current_op.id,
                    "result": result,
                    "disposition": disposition,
                    "quality_state": unit.quality_state,
                },
            )

            if disposition == "scrap":
                self._record_unit_transition(
                    unit,
                    state=ProductionUnitState.TERMINAL,
                    location="terminal",
                    time_ns=k.current_time_ns,
                    details={"station_id": station_id, "operation_id": current_op.id, "reason": "quality_inspection_scrap"},
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
            self._record_unit_transition(
                self.units[unit_id],
                state=ProductionUnitState.IN_STATION,
                location=station_id,
                time_ns=k.current_time_ns,
                details={"station_id": station_id, "operation_id": next_op.id},
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
                self._record_operation_started(unit_id, station_id, next_op.id, k.current_time_ns)
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
    def create(
        cls,
        cfg: SimulationConfig,
        decision_provider: DecisionProvider | None = None,
        audit_logger: AuditLogger | None = None,
        telemetry_manager: TelemetryManager | None = None,
    ) -> EpisodeEngine:
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
            reserved_route_occupancy={r.id: 0 for r in mf.routes},
        )

        engine = cls(
            config=cfg,
            kernel=kernel,
            topology=topology,
            domain=domain,
            decision_provider=decision_provider,
            audit_logger=audit_logger,
            telemetry_manager=telemetry_manager,
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
        decision_provider: DecisionProvider | None = None,
        audit_logger: AuditLogger | None = None,
        telemetry_manager: TelemetryManager | None = None,
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
        reserved_route_occupancy = {r.id: 0 for r in mf.routes}
        reserved_route_occupancy.update(domain_state.get("reserved_route_occupancy", {}))

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
            reserved_route_occupancy=reserved_route_occupancy,
            resource_waiters=resource_waiters,
            active_operations=active_operations,
            maintenance_waiters=maintenance_waiters,
            active_maintenances=active_maintenances,
        )

        engine = cls(
            config=cfg,
            kernel=kernel,
            topology=topology,
            domain=domain,
            random_occurrence_counters=checkpoint.random_occurrence_counters,
            plugin_metadata=checkpoint.plugin_metadata,
            decision_provider=decision_provider,
            audit_logger=audit_logger,
            telemetry_manager=telemetry_manager,
        )
        if checkpoint.domain_state.get("decision_coordinator"):
            engine.decision_coordinator.restore_state(checkpoint.domain_state.get("decision_coordinator"))
        if checkpoint.domain_state.get("decision_triggers"):
            trig_data = checkpoint.domain_state.get("decision_triggers")
            for t_id, t_state in trig_data.items():
                for trigs in engine.decision_triggers.values():
                    for t in trigs:
                        if t.config.id == t_id:
                            t.restore_state(t_state)
        engine.decision_diagnostics = list(checkpoint.domain_state.get("decision_diagnostics", []))
        engine.decision_batches = list(checkpoint.domain_state.get("decision_batches", []))
        return engine

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
            reserved_route_occupancy=dict(self.reserved_route_occupancy),
            in_flight_to=dict(self.in_flight_to),
            source_pending_units={k: list(v) for k, v in self.source_pending_units.items()},
            resource_waiters=list(self.resource_waiters),
            active_operations={k: dict(v) for k, v in self.active_operations.items()},
            maintenance_waiters=list(self.maintenance_waiters),
            active_maintenances={k: dict(v) for k, v in self.active_maintenances.items()},
            decision_triggers={
                trig.config.id: trig.to_snapshot()
                for trigs in self.decision_triggers.values()
                for trig in trigs
            },
            decision_coordinator=self.decision_coordinator.to_snapshot(),
            decision_diagnostics=list(self.decision_diagnostics),
            decision_batches=list(self.decision_batches),
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

    def _check_runtime_hard_constraints(self) -> None:
        if self.is_aborted or not self.cfg.hard_constraints:
            return

        hc = self.cfg.hard_constraints
        curr_metrics = self._compute_current_metrics()

        # 1. Scrap check (respecting warm-up exclusion)
        if hc.max_scrap is not None:
            actual_scrap = curr_metrics["scrap"]
            if actual_scrap > hc.max_scrap:
                self.audit_logger.record(
                    event_type="hard_constraint_violation",
                    simulated_time_ns=self.kernel.current_time_ns,
                    episode_id=self.episode_id,
                    branch_id=getattr(self.decision_coordinator, "branch_id", None),
                    details={
                        "code": "MAX_SCRAP_EXCEEDED",
                        "max_scrap": hc.max_scrap,
                        "actual_scrap": actual_scrap,
                    },
                )
                if hc.terminate_on_violation:
                    self.is_aborted = True
                    self.abort_reason = (
                        f"HARD_CONSTRAINT_VIOLATION: max_scrap limit exceeded "
                        f"({actual_scrap} > {hc.max_scrap})"
                    )
                    return

        # 2. Downtime check
        if hc.max_downtime_ns is not None:
            actual_downtime = curr_metrics["downtime_ns"]
            if actual_downtime > hc.max_downtime_ns:
                self.audit_logger.record(
                    event_type="hard_constraint_violation",
                    simulated_time_ns=self.kernel.current_time_ns,
                    episode_id=self.episode_id,
                    branch_id=getattr(self.decision_coordinator, "branch_id", None),
                    details={
                        "code": "MAX_DOWNTIME_EXCEEDED",
                        "max_downtime_ns": hc.max_downtime_ns,
                        "actual_downtime_ns": actual_downtime,
                    },
                )
                if hc.terminate_on_violation:
                    self.is_aborted = True
                    self.abort_reason = (
                        f"HARD_CONSTRAINT_VIOLATION: max_downtime limit exceeded "
                        f"({actual_downtime} > {hc.max_downtime_ns})"
                    )
                    return

        # 3. Lead time check
        if hc.max_lead_time_ns is not None:
            actual_lead_time = curr_metrics["lead_time_ns"]
            if actual_lead_time > hc.max_lead_time_ns:
                self.audit_logger.record(
                    event_type="hard_constraint_violation",
                    simulated_time_ns=self.kernel.current_time_ns,
                    episode_id=self.episode_id,
                    branch_id=getattr(self.decision_coordinator, "branch_id", None),
                    details={
                        "code": "MAX_LEAD_TIME_EXCEEDED",
                        "max_lead_time_ns": hc.max_lead_time_ns,
                        "actual_lead_time_ns": actual_lead_time,
                    },
                )
                if hc.terminate_on_violation:
                    self.is_aborted = True
                    self.abort_reason = (
                        f"HARD_CONSTRAINT_VIOLATION: max_lead_time limit exceeded "
                        f"({actual_lead_time} > {hc.max_lead_time_ns})"
                    )
                    return

        # 4. Buffer capacity check
        if hc.enforce_buffer_capacity:
            for b in self.buffers.values():
                if len(b.occupants) > b.capacity:
                    self.audit_logger.record(
                        event_type="hard_constraint_violation",
                        simulated_time_ns=self.kernel.current_time_ns,
                        episode_id=self.episode_id,
                        branch_id=getattr(self.decision_coordinator, "branch_id", None),
                        details={
                            "code": "BUFFER_CAPACITY_VIOLATION",
                            "buffer_id": b.id,
                            "capacity": b.capacity,
                            "occupancy": len(b.occupants),
                        },
                    )
                    if hc.terminate_on_violation:
                        self.is_aborted = True
                        self.abort_reason = (
                            f"HARD_CONSTRAINT_VIOLATION: buffer capacity exceeded on {b.id} "
                            f"({len(b.occupants)} > {b.capacity})"
                        )
                        return

    def run(
        self,
        pause_at_ns: int | None = None,
        pause_at_decision_batch: bool = False,
    ) -> EpisodeSummary:
        max_t = pause_at_ns
        if self.cfg.episode.end_condition.max_time_ns is not None:
            if max_t is None:
                max_t = self.cfg.episode.end_condition.max_time_ns
            else:
                max_t = min(max_t, self.cfg.episode.end_condition.max_time_ns)

        self._check_runtime_hard_constraints()
        while self.kernel.queue_size > 0 and not self.is_aborted and not self.is_deadlocked:
            if self._is_terminal_condition_met(self.kernel):
                break

            has_more_events_at_same_time = (
                self.kernel.peek_next_time() == self.kernel.current_time_ns
            )
            if not has_more_events_at_same_time and self.decision_coordinator.has_pending():
                if pause_at_decision_batch:
                    return self.to_summary()
                self._process_decision_batch()
                self._check_runtime_hard_constraints()
                if self.is_aborted or self.is_deadlocked:
                    break

            next_time = self.kernel.peek_next_time()
            if next_time is None or (max_t is not None and next_time > max_t):
                break

            self.kernel.step()
            self._check_runtime_hard_constraints()

            if self.is_aborted or self.is_deadlocked:
                break

            has_more_events_at_same_time = (
                self.kernel.peek_next_time() == self.kernel.current_time_ns
            )
            if not has_more_events_at_same_time and self.decision_coordinator.has_pending():
                if pause_at_decision_batch:
                    return self.to_summary()
                self._process_decision_batch()
                self._check_runtime_hard_constraints()
                if self.is_aborted or self.is_deadlocked:
                    break

            if self._is_terminal_condition_met(self.kernel):
                break

        if not self.is_aborted and not self.is_deadlocked and self.decision_coordinator.has_pending():
            if not pause_at_decision_batch:
                self._process_decision_batch()

        # Check for deadlock if unfinished, not aborted/deadlocked, and deadlock detection enabled
        if (
            not self.is_aborted
            and not self.is_deadlocked
            and not self._is_terminal_condition_met(self.kernel)
            and (self.cfg.deadlock is None or self.cfg.deadlock.enabled)
        ):
            diagnosis = analyze_deadlock(self)
            if diagnosis is not None:
                self._terminate_with_deadlock(diagnosis)

        if not self.is_aborted and not self.is_deadlocked and not self._is_terminal_condition_met(self.kernel):
            if not (pause_at_decision_batch and self.decision_coordinator.has_pending()):
                if pause_at_ns is not None and self.kernel.current_time_ns < pause_at_ns:
                    self.kernel.advance_to(pause_at_ns)

        summary = self.to_summary()
        if not pause_at_decision_batch:
            if self.is_telemetry_enabled:
                self._sample_telemetry(sample_type="terminal", event_name="episode_end")
            self.audit_logger.record(
                event_type="reward",
                simulated_time_ns=self.kernel.current_time_ns,
                episode_id=self.episode_id,
                branch_id=getattr(self.decision_coordinator, "branch_id", None),
                details={
                    "reward": summary.reward,
                    "reward_breakdown": summary.reward_breakdown,
                    "total_strategic_cost": self.total_strategic_cost,
                    "events_processed": self.kernel.events_processed,
                },
            )

        return summary

    def to_summary(self) -> EpisodeSummary:
        all_terminal = self._is_terminal_condition_met(self.kernel)
        if self.is_deadlocked:
            status = "deadlocked"
        elif self.is_aborted:
            status = "aborted"
        elif all_terminal:
            status = "completed"
        else:
            status = "incomplete"

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
            decision_batches=self.decision_batches,
            decision_diagnostics=self.decision_diagnostics,
            deadlock_diagnosis=self.deadlock_diagnosis.to_dict() if self.deadlock_diagnosis else None,
        )

        summary_obj = EpisodeSummary(
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
            decision_batches=list(self.decision_batches),
            decision_diagnostics=list(self.decision_diagnostics),
            is_aborted=self.is_aborted,
            abort_reason=self.abort_reason,
            is_deadlocked=self.is_deadlocked,
            deadlock_diagnosis=self.deadlock_diagnosis.to_dict() if self.deadlock_diagnosis else None,
            total_cost=self.total_strategic_cost,
            total_strategic_cost=self.total_strategic_cost,
            result_hash=result_hash,
        )
        raw_metrics = _compute_raw_metrics(summary_obj, warm_up_time_ns=self.cfg.episode.warm_up_time_ns)
        reward, reward_breakdown = _compute_reward(raw_metrics, self.cfg.reward_policy)
        hard_constraints = _compute_hard_constraints(
            summary_obj, self.cfg.hard_constraints, raw_metrics=raw_metrics
        )
        object.__setattr__(summary_obj, "raw_metrics", raw_metrics)
        object.__setattr__(summary_obj, "reward", reward)
        object.__setattr__(summary_obj, "reward_breakdown", reward_breakdown)
        object.__setattr__(summary_obj, "hard_constraints", hard_constraints)
        return summary_obj


def create_checkpoint(
    source: str | Path | dict[str, Any] | SimulationConfig | EpisodeEngine,
    at_time_ns: int | None = None,
    pause_at_decision_batch: bool = False,
    decision_provider: DecisionProvider | None = None,
) -> Checkpoint:
    if isinstance(source, EpisodeEngine):
        engine = source
        if decision_provider is not None:
            engine.decision_provider = decision_provider
        if at_time_ns is not None and at_time_ns < engine.kernel.current_time_ns:
            raise ValueError(
                f"Cannot create checkpoint at {at_time_ns} ns: engine has already advanced past this time to {engine.kernel.current_time_ns} ns"
            )
    else:
        if isinstance(source, SimulationConfig):
            cfg = source
        else:
            validation = validate_config(source)
            if not validation.is_valid or validation.config is None:
                raise ValueError(f"Invalid configuration: {'; '.join(validation.errors)}")
            cfg = validation.config

        if at_time_ns is not None and at_time_ns < cfg.episode.start_time_ns:
            raise ValueError(
                f"Cannot create checkpoint at {at_time_ns} ns: episode start time is {cfg.episode.start_time_ns} ns"
            )
        engine = EpisodeEngine.create(cfg, decision_provider=decision_provider)

    if pause_at_decision_batch:
        engine.run(pause_at_ns=at_time_ns, pause_at_decision_batch=True)
    elif at_time_ns is not None and at_time_ns > engine.kernel.current_time_ns:
        engine.run(pause_at_ns=at_time_ns)

    return engine.create_checkpoint()


def restore_checkpoint(
    checkpoint: str | Path | dict[str, Any] | Checkpoint,
    config: str | Path | dict[str, Any] | SimulationConfig | None = None,
    decision_provider: DecisionProvider | None = None,
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

    return EpisodeEngine.restore(cp, config=cfg, decision_provider=decision_provider)


def continue_checkpoint(
    checkpoint: str | Path | dict[str, Any] | Checkpoint,
    config_source: str | Path | dict[str, Any] | SimulationConfig | None = None,
    until_time_ns: int | None = None,
    decision_provider: DecisionProvider | None = None,
) -> EpisodeSummary:
    engine = restore_checkpoint(checkpoint, config=config_source, decision_provider=decision_provider)
    return engine.run(pause_at_ns=until_time_ns)


def resume_episode(
    checkpoint: str | Path | dict[str, Any] | Checkpoint,
    config_source: str | Path | dict[str, Any] | SimulationConfig | None = None,
    decision_provider: DecisionProvider | None = None,
) -> EpisodeSummary:
    return continue_checkpoint(checkpoint, config_source=config_source, decision_provider=decision_provider)


def run_episode(
    source: str | Path | dict[str, Any],
    decision_provider: DecisionProvider | None = None,
    output_dir: str | Path | None = None,
) -> EpisodeSummary:
    validation = validate_config(source)
    if not validation.is_valid or validation.config is None:
        raise ValueError(f"Invalid configuration: {'; '.join(validation.errors)}")

    cfg = validation.config
    writer: RunArtifactWriter | None = None
    audit_logger: AuditLogger | None = None

    if output_dir is not None:
        episode_id = f"ep-{cfg.seed}"
        writer = RunArtifactWriter(
            output_dir=output_dir,
            config=cfg,
            episode_id=episode_id,
        )
        audit_logger = writer.audit_logger

    engine = EpisodeEngine.create(
        cfg,
        decision_provider=decision_provider,
        audit_logger=audit_logger,
        telemetry_manager=writer.telemetry_manager if writer is not None else None,
    )
    summary = engine.run()

    if writer is not None:
        final_cp = engine.create_checkpoint()
        save_checkpoint(final_cp, writer.checkpoints_dir / "final_checkpoint.json")
        writer.finalize(summary.to_dict(), status=summary.status)

    return summary


@dataclass(frozen=True)
class CounterfactualBranchResult:
    branch_id: str
    actions: list[dict[str, Any]]
    provenance: DecisionProvenance
    raw_metrics: dict[str, Any]
    hard_constraints: dict[str, Any]
    summary: EpisodeSummary
    result_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "branch_id": self.branch_id,
            "actions": self.actions,
            "provenance": self.provenance.model_dump(mode="json"),
            "raw_metrics": self.raw_metrics,
            "hard_constraints": self.hard_constraints,
            "summary": self.summary.to_dict(),
            "result_hash": self.result_hash,
        }


@dataclass(frozen=True)
class BranchComparisonResult:
    checkpoint_config_hash: str
    checkpoint_time_ns: int
    decision_batch_id: str
    branches: list[CounterfactualBranchResult]

    def to_dict(self) -> dict[str, Any]:
        return {
            "checkpoint_config_hash": self.checkpoint_config_hash,
            "checkpoint_time_ns": self.checkpoint_time_ns,
            "decision_batch_id": self.decision_batch_id,
            "branches": [b.to_dict() for b in self.branches],
        }


def _parse_action_set(
    action_input: Any,
) -> tuple[str | None, str | None, str | None, list[DecisionAction]]:
    action_adapter: TypeAdapter[DecisionAction] = TypeAdapter(DecisionAction)

    if isinstance(action_input, DecisionBatchResponse):
        prov = action_input.provenance
        return prov.provider_id, prov.model_id, prov.prompt_id, list(action_input.actions)

    provider_id: str | None = None
    model_id: str | None = None
    prompt_id: str | None = None
    raw_actions: list[Any] = []

    if isinstance(action_input, dict):
        if "action_type" in action_input:
            raw_actions = [action_input]
        else:
            provider_id = action_input.get("provider_id")
            model_id = action_input.get("model_id")
            prompt_id = action_input.get("prompt_id")
            raw_actions = action_input.get("actions", [])
    elif isinstance(action_input, (list, tuple)):
        raw_actions = list(action_input)
    else:
        raw_actions = [action_input]

    parsed_actions: list[DecisionAction] = []
    for item in raw_actions:
        if isinstance(
            item,
            (
                BufferReorderAction,
                RoutingAction,
                DispatchAction,
                MachineModeAction,
                MaintenanceAction,
                ReconfigurationAction,
                WorkerReassignmentAction,
                QualityControlAction,
            ),
        ):
            parsed_actions.append(item)
        else:
            parsed_actions.append(action_adapter.validate_python(item))

    return provider_id, model_id, prompt_id, parsed_actions


def _derive_branch_id(
    config_hash: str,
    root_seed: int,
    simulated_time_ns: int,
    actions: Sequence[DecisionAction],
) -> str:
    # Sort action representations to ensure set order invariance
    serialized_actions = [
        json.dumps(a.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        for a in actions
    ]
    canonical_actions = json.dumps(sorted(serialized_actions), separators=(",", ":"))
    action_hash = hashlib.sha256(canonical_actions.encode("utf-8")).hexdigest()[:12]
    material = f"{config_hash}:{root_seed}:{simulated_time_ns}:{action_hash}".encode("utf-8")
    digest = hashlib.sha256(material).hexdigest()[:12]
    return f"branch-{digest}"


def _compute_raw_metrics(summary: EpisodeSummary, warm_up_time_ns: int = 0) -> dict[str, Any]:
    # Good output: completed units at sink with quality_state != 'scrapped' and terminal >= warm_up_time_ns
    good_completed_units = [
        u
        for u in summary.production_units
        if u.state == "terminal"
        and u.location != "scrapped"
        and u.quality_state != "scrapped"
        and (not u.history or u.history[-1]["time_ns"] >= warm_up_time_ns)
    ]
    good_output = len(good_completed_units)

    # Scrap: units in terminal state marked as scrapped with terminal transition >= warm_up_time_ns
    scrap_units = [
        u
        for u in summary.production_units
        if u.state == "terminal"
        and (u.location == "scrapped" or u.quality_state == "scrapped")
        and (not u.history or u.history[-1]["time_ns"] >= warm_up_time_ns)
    ]
    scrap = len(scrap_units)

    # WIP: units released but not terminal
    wip = sum(
        1
        for u in summary.production_units
        if u.state not in ("created", "terminal")
    )
    # Good completed units for lead time and lateness (exclude scrapped units!)
    if good_completed_units:
        total_lead_time_ns = sum(
            u.history[-1]["time_ns"] - u.history[0]["time_ns"]
            for u in good_completed_units
            if u.history
        )
        lead_time_ns = int(round(total_lead_time_ns / len(good_completed_units)))
    else:
        lead_time_ns = 0

    # Downtime (ns): sum of failed time and maintenance time across machines
    downtime_ns = sum(
        m.total_failed_time_ns + m.total_maintenance_time_ns
        for m in summary.machines
    )

    # Lateness (ns): total lateness beyond due date for good completed units
    lateness_ns = sum(
        max(0, u.history[-1]["time_ns"] - u.due_date_ns)
        for u in good_completed_units
        if u.due_date_ns is not None and u.history
    )

    # Resource utilization
    resource_utilization = {
        "machines": {m.id: m.utilization for m in summary.machines},
        "workers": {w.id: w.utilization for w in summary.workers},
        "vehicles": {v.id: v.utilization for v in summary.vehicles},
    }

    return {
        "good_output": good_output,
        "lead_time_ns": lead_time_ns,
        "wip": wip,
        "scrap": scrap,
        "downtime_ns": downtime_ns,
        "lateness_ns": lateness_ns,
        "resource_utilization": resource_utilization,
        "total_strategic_cost": summary.total_strategic_cost,
    }


def _compute_reward(
    raw_metrics: dict[str, Any], policy: RewardPolicyConfig | None
) -> tuple[float | None, dict[str, float]]:
    if policy is None or not policy.components:
        return None, {}
    breakdown: dict[str, float] = {}
    total = 0.0
    for comp in policy.components:
        val = raw_metrics.get(comp.name)
        if val is None:
            continue
        if isinstance(val, dict):
            flat_vals: list[float] = []
            for sub in val.values():
                if isinstance(sub, dict):
                    flat_vals.extend(float(x) for x in sub.values())
                elif isinstance(sub, (int, float)):
                    flat_vals.append(float(sub))
            val = sum(flat_vals) / len(flat_vals) if flat_vals else 0.0
        num_val = float(val)
        scale = comp.scale if comp.scale != 0 else 1.0
        if comp.target is not None:
            norm_val = -abs(num_val - comp.target) / scale
        else:
            norm_val = (num_val - comp.offset) / scale
            if comp.direction == "minimize":
                norm_val = -norm_val
        c_reward = comp.weight * norm_val
        breakdown[comp.name] = c_reward
        total += c_reward
    return total, breakdown



def _compute_hard_constraints(
    summary: EpisodeSummary,
    config: HardConstraintsConfig | None = None,
    raw_metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    violations: list[dict[str, Any]] = []
    if summary.is_aborted:
        violations.append(
            {
                "code": "EPISODE_ABORTED",
                "reason": summary.abort_reason or "Unknown abort reason",
            }
        )
    for b in summary.buffers:
        if b.peak_occupancy > b.capacity:
            violations.append(
                {
                    "code": "BUFFER_CAPACITY_VIOLATION",
                    "buffer_id": b.id,
                    "capacity": b.capacity,
                    "peak_occupancy": b.peak_occupancy,
                }
            )

    metrics = raw_metrics or summary.raw_metrics
    if config is not None:
        if config.max_scrap is not None:
            actual_scrap = metrics.get("scrap", 0)
            if actual_scrap > config.max_scrap:
                violations.append(
                    {
                        "code": "MAX_SCRAP_EXCEEDED",
                        "max_scrap": config.max_scrap,
                        "actual_scrap": actual_scrap,
                    }
                )
        if config.max_downtime_ns is not None:
            actual_downtime = metrics.get("downtime_ns", 0)
            if actual_downtime > config.max_downtime_ns:
                violations.append(
                    {
                        "code": "MAX_DOWNTIME_EXCEEDED",
                        "max_downtime_ns": config.max_downtime_ns,
                        "actual_downtime_ns": actual_downtime,
                    }
                )
        if config.max_lead_time_ns is not None:
            actual_lead_time = metrics.get("lead_time_ns", 0)
            if actual_lead_time > config.max_lead_time_ns:
                violations.append(
                    {
                        "code": "MAX_LEAD_TIME_EXCEEDED",
                        "max_lead_time_ns": config.max_lead_time_ns,
                        "actual_lead_time_ns": actual_lead_time,
                    }
                )

    satisfied = (len(violations) == 0) and not summary.is_aborted
    return {
        "satisfied": satisfied,
        "violations": violations,
        "aborted": summary.is_aborted,
        "abort_reason": summary.abort_reason,
    }


def branch_checkpoint(
    checkpoint: str | Path | dict[str, Any] | Checkpoint,
    alternative_actions: Sequence[Any],
    config_source: str | Path | dict[str, Any] | SimulationConfig | None = None,
    output_dir: str | Path | None = None,
) -> BranchComparisonResult:
    if len(alternative_actions) < 2:
        raise ValueError(
            f"Counterfactual branching requires at least two alternative Action sets, got {len(alternative_actions)}"
        )

    out_p: Path | None = Path(output_dir) if output_dir is not None else None
    root_created_at = datetime.now(timezone.utc).isoformat()

    if out_p is not None:
        manifest_p = out_p / "manifest.json"
        if manifest_p.exists():
            try:
                m_data = json.loads(manifest_p.read_text(encoding="utf-8"))
                if m_data.get("status") == "completed":
                    raise RunArtifactExistsError(
                        f"Run directory '{output_dir}' already exists and is completed"
                    )
            except (json.JSONDecodeError, OSError):
                pass
        out_p.mkdir(parents=True, exist_ok=True)
        (out_p / ".incomplete").write_text("in_progress\n", encoding="utf-8")

    if isinstance(checkpoint, (str, Path)):
        cp = load_checkpoint(checkpoint)
    elif isinstance(checkpoint, dict):
        cp = deserialize_checkpoint(checkpoint)
    elif isinstance(checkpoint, Checkpoint):
        cp = checkpoint
    else:
        raise TypeError(f"Unsupported checkpoint type: {type(checkpoint).__name__}")

    if out_p is not None:
        cp_dir = out_p / "checkpoints"
        cp_dir.mkdir(exist_ok=True)
        save_checkpoint(cp, cp_dir / "parent_checkpoint.json")

    cfg: SimulationConfig | None = None
    if config_source is not None:
        if isinstance(config_source, SimulationConfig):
            cfg = config_source
        else:
            validation = validate_config(config_source)
            if not validation.is_valid or validation.config is None:
                raise ValueError(f"Invalid configuration: {'; '.join(validation.errors)}")
            cfg = validation.config

    # Verify that the checkpoint is at a Decision Batch
    coord = (
        cp.domain_state.get("decision_coordinator")
        if hasattr(cp.domain_state, "get")
        else getattr(cp.domain_state, "decision_coordinator", None)
    )
    if isinstance(coord, dict):
        pending = coord.get("pending_requests", [])
    elif hasattr(coord, "pending_requests"):
        pending = getattr(coord, "pending_requests")
    else:
        pending = []

    if not pending:
        raise ValueError(
            "Checkpoint is not at a Decision Batch: no pending decision requests found in checkpoint."
        )

    branch_results: list[CounterfactualBranchResult] = []
    batch_id: str = "unknown"

    for alt in alternative_actions:
        provider_id, model_id, prompt_id, actions = _parse_action_set(alt)
        branch_id = _derive_branch_id(
            config_hash=cp.config_hash,
            root_seed=cp.root_seed,
            simulated_time_ns=cp.simulated_time_ns,
            actions=actions,
        )

        branch_writer: RunArtifactWriter | None = None
        branch_audit_logger: AuditLogger | None = None

        if out_p is not None:
            branch_dir = out_p / "branches" / branch_id
            eff_cfg = cfg
            if eff_cfg is None:
                eff_cfg = SimulationConfig.model_validate(cp.configuration)
            branch_writer = RunArtifactWriter(
                output_dir=branch_dir,
                config=eff_cfg,
                episode_id=f"ep-{cp.root_seed}-{branch_id}",
                branch_id=branch_id,
                parent_run_id=f"ep-{cp.root_seed}",
                checkpoint_hash=cp.config_hash,
            )
            branch_audit_logger = branch_writer.audit_logger

        # Restore isolated engine for this branch
        engine = EpisodeEngine.restore(
            cp,
            config=cfg,
            audit_logger=branch_audit_logger,
            telemetry_manager=branch_writer.telemetry_manager if branch_writer is not None else None,
        )
        engine.decision_coordinator.branch_id = branch_id
        engine.random_occurrence_counters = dict(cp.random_occurrence_counters)
        engine.random_stream = SemanticRandomStream(
            root_seed=engine.cfg.seed,
            occurrence_counters=engine.random_occurrence_counters,
        )

        # Form the decision batch
        batch = engine.decision_coordinator.form_batch(
            time_ns=engine.kernel.current_time_ns,
            observation_builder=lambda req: engine._build_observation_for_request(
                req, engine.kernel.current_time_ns
            ),
        )
        if batch is None:
            raise ValueError("Failed to form Decision Batch from checkpoint pending requests.")

        batch = batch.model_copy(update={"branch_id": branch_id})
        batch_id = batch.batch_id

        # Validate and apply actions with full provenance contract
        provenance = DecisionProvenance(
            episode_id=batch.episode_id,
            branch_id=branch_id,
            batch_id=batch.batch_id,
            provider_id=provider_id or f"action-set-{branch_id}",
            model_id=model_id,
            prompt_id=prompt_id,
        )
        response = DecisionBatchResponse(
            batch_id=batch.batch_id,
            provenance=provenance,
            actions=actions,
        )

        is_valid, diagnostics = validate_decision_batch_response(batch, response)

        # Log decision requests, proposed actions, and validation outcome into branch audit log
        for req in batch.requests:
            engine.audit_logger.record(
                event_type="decision_request",
                simulated_time_ns=engine.kernel.current_time_ns,
                episode_id=batch.episode_id,
                branch_id=branch_id,
                batch_id=batch.batch_id,
                entity_ids=[req.target_id],
                details={
                    "request_id": req.request_id,
                    "request_type": req.request_type,
                    "target_id": req.target_id,
                    "trigger_id": req.trigger_id,
                    "action_schema": req.action_schema,
                },
            )

        for act in actions:
            t_id = (
                getattr(act, "buffer_id", None)
                or getattr(act, "target_id", None)
                or getattr(act, "machine_id", None)
                or getattr(act, "node_id", None)
                or getattr(act, "unit_id", None)
            )
            entity_ids = [t_id] if t_id else []
            engine.audit_logger.record(
                event_type="decision_action",
                simulated_time_ns=engine.kernel.current_time_ns,
                episode_id=batch.episode_id,
                branch_id=branch_id,
                batch_id=batch.batch_id,
                entity_ids=entity_ids,
                provenance=provenance.model_dump(mode="json"),
                details={
                    "action_type": act.action_type,
                    "action": act.model_dump(mode="json"),
                },
            )

        engine.audit_logger.record(
            event_type="validation_outcome",
            simulated_time_ns=engine.kernel.current_time_ns,
            episode_id=batch.episode_id,
            branch_id=branch_id,
            batch_id=batch.batch_id,
            details={
                "is_valid": is_valid,
                "diagnostics": [d.model_dump(mode="json") for d in diagnostics],
            },
        )

        if is_valid:
            engine._apply_decision_actions(batch, response)
        else:
            engine._handle_decision_failure(batch, diagnostics)

        # Continue branch execution to episode completion
        summary = engine.run()

        if branch_writer is not None:
            branch_cp = engine.create_checkpoint()
            save_checkpoint(branch_cp, branch_writer.checkpoints_dir / "final_checkpoint.json")
            branch_writer.finalize(
                summary.to_dict(),
                status=summary.status,
            )

        # The actions actually applied in this branch
        applied_actions = (
            engine.decision_batches[-1].get("actions", [a.model_dump(mode="json") for a in actions])
            if engine.decision_batches
            else [a.model_dump(mode="json") for a in actions]
        )

        raw_metrics = _compute_raw_metrics(summary)
        hard_constraints = _compute_hard_constraints(summary)

        branch_results.append(
            CounterfactualBranchResult(
                branch_id=branch_id,
                actions=applied_actions,
                provenance=provenance,
                raw_metrics=raw_metrics,
                hard_constraints=hard_constraints,
                summary=summary,
                result_hash=summary.result_hash,
            )
        )

    comp_result = BranchComparisonResult(
        checkpoint_config_hash=cp.config_hash,
        checkpoint_time_ns=cp.simulated_time_ns,
        decision_batch_id=batch_id,
        branches=branch_results,
    )

    if out_p is not None:
        (out_p / "comparison_summary.json").write_text(
            json.dumps(comp_result.to_dict(), indent=2), encoding="utf-8"
        )
        eff_cfg = cfg or SimulationConfig.model_validate(cp.configuration)
        buf = StringIO()
        _yaml.dump(eff_cfg.model_dump(mode="json"), buf)
        (out_p / "resolved_config.yaml").write_text(buf.getvalue(), encoding="utf-8")

        root_manifest = {
            "schema_version": cp.schema_version,
            "kernel_version": cp.kernel_version,
            "run_id": f"branch-comp-{cp.config_hash[:8]}-{cp.simulated_time_ns}",
            "type": "branch_comparison",
            "status": "completed",
            "created_at": root_created_at,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "decision_batch_id": batch_id,
            "checkpoint_config_hash": cp.config_hash,
            "config_hash": cp.config_hash,
            "model_hash": cp.model_hash,
            "checkpoint_time_ns": cp.simulated_time_ns,
            "branches": [
                {
                    "branch_id": b.branch_id,
                    "result_hash": b.result_hash,
                    "path": f"branches/{b.branch_id}",
                }
                for b in branch_results
            ],
            "runtime": collect_runtime_metadata(),
            "libraries": collect_library_metadata(),
            "seed": cp.root_seed,
            "calibration": collect_calibration_metadata(),
            "plugin_metadata": cp.plugin_metadata,
        }
        (out_p / "manifest.json").write_text(json.dumps(root_manifest, indent=2), encoding="utf-8")
        if (out_p / ".incomplete").exists():
            (out_p / ".incomplete").unlink()

    return comp_result



