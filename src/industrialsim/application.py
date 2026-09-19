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
    Buffer,
    Operation,
    ProductionUnit,
    ProductionUnitState,
    Station,
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

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "operations_completed": self.operations_completed,
            "total_busy_time_ns": self.total_busy_time_ns,
            "total_blocked_time_ns": self.total_blocked_time_ns,
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

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "seed": self.seed,
            "simulated_time_ns": self.simulated_time_ns,
            "events_processed": self.events_processed,
            "production_units": [u.to_dict() for u in self.production_units],
            "stations": [s.to_dict() for s in self.stations],
            "buffers": [b.to_dict() for b in self.buffers],
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
) -> str:
    data = {
        "status": status,
        "seed": seed,
        "simulated_time_ns": simulated_time_ns,
        "events_processed": events_processed,
        "production_units": [u.to_dict() for u in units],
        "stations": [s.to_dict() for s in stations],
        "buffers": [b.to_dict() for b in (buffers or [])],
    }
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
    ProductionUnitSnapshot,
    StationSnapshot,
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

    def _setup_handlers(self) -> None:
        self.kernel.register_handler("RELEASE_UNIT", self._handle_release)
        self.kernel.register_handler("ARRIVAL_AT_NODE", self._handle_arrival_at_node)
        self.kernel.register_handler("COMPLETE_OPERATION", self._handle_complete_operation)

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

    def _handle_station_arrival(self, k: EventKernel, unit_id: str, node_id: str) -> None:
        st = self.stations[node_id]
        assert st.can_accept(), f"Station {node_id} accepted unit {unit_id} while busy/blocked"
        op = list(st.operations.values())[0]
        st.start_operation(unit_id, op.id, k.current_time_ns)
        self.units[unit_id].record_transition(
            time_ns=k.current_time_ns,
            state=ProductionUnitState.IN_STATION,
            location=node_id,
            station_id=node_id,
            operation_id=op.id,
        )
        k.schedule(
            time_ns=k.current_time_ns + op.duration_ns,
            priority=EventPriority.COMPLETION,
            event_type="COMPLETE_OPERATION",
            payload={"unit_id": unit_id, "station_id": node_id, "op_index": 0},
        )

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
        st = self.stations[station_id]
        ops_list = list(st.operations.values())
        current_op = ops_list[op_index]

        st.complete_operation(current_op.id, k.current_time_ns)

        # If station has multiple operations and more remain for this unit:
        if op_index + 1 < len(ops_list):
            next_op = ops_list[op_index + 1]
            st.start_operation(unit_id, next_op.id, k.current_time_ns)
            self.units[unit_id].record_transition(
                time_ns=k.current_time_ns,
                state=ProductionUnitState.IN_STATION,
                location=station_id,
                station_id=station_id,
                operation_id=next_op.id,
            )
            k.schedule(
                time_ns=k.current_time_ns + next_op.duration_ns,
                priority=EventPriority.COMPLETION,
                event_type="COMPLETE_OPERATION",
                payload={"unit_id": unit_id, "station_id": station_id, "op_index": op_index + 1},
            )
            return

        # Last operation completed for this unit:
        route = self._get_available_route(station_id)
        downstream_can_accept = route is not None and self._can_accept(route.target_node_id)

        if downstream_can_accept and route is not None:
            self._dispatch_unit_to_target(k, unit_id, route)
            self._try_pull_upstream(k, station_id)
        else:
            if st.has_output_space():
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
                        op.id: Operation(id=op.id, duration_ns=op.duration_ns)
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

        topology = MaterialFlowTopology.from_material_flow(mf)
        domain = SimulationDomainState(
            units=units,
            stations=stations,
            buffers=buffers,
            in_flight_to=in_flight_to,
            source_pending_units=source_pending_units,
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
            provided_model_hash = compute_model_hash(config)
            if provided_model_hash != checkpoint.model_hash:
                raise IncompatibleCheckpointError(
                    f"Model hash mismatch: checkpoint requires '{checkpoint.model_hash}', but provided model has '{provided_model_hash}'"
                )
            provided_config_hash = compute_config_hash(config)
            if provided_config_hash != checkpoint.config_hash:
                raise IncompatibleCheckpointError(
                    f"Configuration hash mismatch: checkpoint requires '{checkpoint.config_hash}', but provided config has '{provided_config_hash}'"
                )
            cfg = config
        else:
            if not checkpoint.configuration:
                raise IncompatibleCheckpointError(
                    "Checkpoint contains no embedded configuration, and no configuration was provided"
                )
            cfg = SimulationConfig.model_validate(checkpoint.configuration)
            embedded_model_hash = compute_model_hash(cfg)
            if embedded_model_hash != checkpoint.model_hash:
                raise IncompatibleCheckpointError(
                    f"Model hash mismatch: checkpoint requires '{checkpoint.model_hash}', but embedded model has '{embedded_model_hash}'"
                )
            embedded_config_hash = compute_config_hash(cfg)
            if embedded_config_hash != checkpoint.config_hash:
                raise IncompatibleCheckpointError(
                    f"Configuration hash mismatch: checkpoint requires '{checkpoint.config_hash}', but embedded config has '{embedded_config_hash}'"
                )

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
                    op.id: Operation(id=op.id, duration_ns=op.duration_ns)
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

        in_flight_to = {node.id: 0 for node in mf.nodes}
        in_flight_to.update(domain_state.get("in_flight_to", {}))

        source_pending_units = {
            nid: list(domain_state.get("source_pending_units", {}).get(nid, []))
            for nid in sources
        }

        topology = MaterialFlowTopology.from_material_flow(mf)
        domain = SimulationDomainState(
            units=units,
            stations=stations,
            buffers=buffers,
            in_flight_to=in_flight_to,
            source_pending_units=source_pending_units,
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
            in_flight_to=dict(self.in_flight_to),
            source_pending_units={k: list(v) for k, v in self.source_pending_units.items()},
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

        result_hash = _compute_result_hash(
            status=status,
            seed=self.cfg.seed,
            simulated_time_ns=self.kernel.current_time_ns,
            events_processed=self.kernel.events_processed,
            units=unit_summaries,
            stations=station_summaries,
            buffers=buffer_summaries,
        )

        return EpisodeSummary(
            status=status,
            seed=self.cfg.seed,
            simulated_time_ns=self.kernel.current_time_ns,
            events_processed=self.kernel.events_processed,
            production_units=unit_summaries,
            stations=station_summaries,
            buffers=buffer_summaries,
            result_hash=result_hash,
        )


def create_checkpoint(
    source: str | Path | dict[str, Any] | SimulationConfig | EpisodeEngine,
    at_time_ns: int | None = None,
) -> Checkpoint:
    if isinstance(source, EpisodeEngine):
        engine = source
        if at_time_ns is not None and at_time_ns > engine.kernel.current_time_ns:
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
    if at_time_ns is not None and at_time_ns > cfg.episode.start_time_ns:
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


def run_episode(
    source: str | Path | dict[str, Any],
    checkpoint_at_ns: int | None = None,
    checkpoint_path: str | Path | None = None,
) -> EpisodeSummary:
    validation = validate_config(source)
    if not validation.is_valid or validation.config is None:
        raise ValueError(f"Invalid configuration: {'; '.join(validation.errors)}")

    cfg = validation.config
    engine = EpisodeEngine.create(cfg)

    if checkpoint_at_ns is not None:
        engine.run(pause_at_ns=checkpoint_at_ns)
        if checkpoint_path is not None:
            cp = engine.create_checkpoint()
            save_checkpoint(cp, checkpoint_path)

    return engine.run()

