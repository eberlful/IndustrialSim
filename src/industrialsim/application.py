from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
from typing import Any
import yaml
from pydantic import ValidationError

from industrialsim.config import SimulationConfig
from industrialsim.domain import (
    Buffer,
    Operation,
    ProductionUnit,
    ProductionUnitState,
    Station,
)
from industrialsim.kernel import EventKernel, EventPriority, ScheduledEvent


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
        parsed = yaml.safe_load(content)
        if not isinstance(parsed, dict):
            raise ValueError(f"YAML at {source} did not produce a dictionary mapping")
        return parsed

    if isinstance(source, str):
        path = Path(source)
        if path.is_file():
            content = path.read_text(encoding="utf-8")
            parsed = yaml.safe_load(content)
        else:
            parsed = yaml.safe_load(source)
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


def run_episode(source: str | Path | dict[str, Any]) -> EpisodeSummary:
    validation = validate_config(source)
    if not validation.is_valid or validation.config is None:
        raise ValueError(f"Invalid configuration: {'; '.join(validation.errors)}")

    cfg = validation.config

    units: dict[str, ProductionUnit] = {
        u_cfg.id: ProductionUnit(id=u_cfg.id, variant=u_cfg.variant)
        for u_cfg in cfg.production_units
    }

    kernel = EventKernel(initial_time_ns=cfg.episode.start_time_ns)

    # Branch: Material Flow Graph vs Minimal Single Station
    if cfg.material_flow is not None:
        mf = cfg.material_flow
        nodes_by_id = {n.id: n for n in mf.nodes}

        stations: dict[str, Station] = {}
        buffers: dict[str, Buffer] = {}
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

        routes_from: dict[str, list[Any]] = {}
        routes_to: dict[str, list[Any]] = {}
        for r in mf.routes:
            routes_from.setdefault(r.source_node_id, []).append(r)
            routes_to.setdefault(r.target_node_id, []).append(r)

        waiting_at_node: dict[str, list[str]] = {n.id: [] for n in mf.nodes}

        def can_accept(node_id: str) -> bool:
            node = nodes_by_id[node_id]
            if node.kind == "sink":
                return True
            if node.kind == "buffer":
                return buffers[node_id].can_accept()
            if node.kind == "station":
                st = stations[node_id]
                return (not st.is_busy) and (not st.is_blocked) and (len(waiting_at_node[node_id]) == 0)
            return False

        def get_available_route(from_node_id: str) -> Any | None:
            routes = routes_from.get(from_node_id, [])
            for r in routes:
                if can_accept(r.target_node_id):
                    return r
            return routes[0] if routes else None

        def dispatch_unit_to_target(k: EventKernel, unit_id: str, route: Any) -> None:
            target_id = route.target_node_id
            units[unit_id].record_transition(
                k.current_time_ns,
                ProductionUnitState.IN_TRANSPORT,
                location=route.id,
            )
            if route.transit_time_ns > 0:
                k.schedule(
                    time_ns=k.current_time_ns + route.transit_time_ns,
                    priority=EventPriority.COMPLETION,
                    event_type="ARRIVAL_AT_NODE",
                    payload={"unit_id": unit_id, "node_id": target_id},
                )
            else:
                k.schedule(
                    time_ns=k.current_time_ns,
                    priority=EventPriority.COMPLETION,
                    event_type="ARRIVAL_AT_NODE",
                    payload={"unit_id": unit_id, "node_id": target_id},
                )

        def try_pull_upstream(k: EventKernel, node_id: str, visited: set[str] | None = None) -> None:
            if visited is None:
                visited = set()
            if node_id in visited:
                return
            visited.add(node_id)

            # Check all routes leading to node_id
            for route in routes_to.get(node_id, []):
                upstream_id = route.source_node_id
                if upstream_id in stations:
                    st = stations[upstream_id]
                    if st.output_buffer and can_accept(node_id):
                        out_uid = st.output_buffer.pop(0)
                        dispatch_unit_to_target(k, out_uid, route)
                        if st.is_blocked:
                            blocked_uid = st.blocked_unit_id
                            assert blocked_uid is not None
                            st.end_blocking(k.current_time_ns)
                            st.output_buffer.append(blocked_uid)
                            units[blocked_uid].record_transition(
                                k.current_time_ns,
                                ProductionUnitState.IN_STATION,
                                location=upstream_id,
                                station_id=upstream_id,
                            )
                            try_start_next_operation(k, upstream_id)
                            try_pull_upstream(k, upstream_id, visited)
                    elif st.is_blocked and can_accept(node_id):
                        blocked_uid = st.blocked_unit_id
                        assert blocked_uid is not None
                        st.end_blocking(k.current_time_ns)
                        dispatch_unit_to_target(k, blocked_uid, route)
                        try_start_next_operation(k, upstream_id)
                        try_pull_upstream(k, upstream_id, visited)
                elif upstream_id in buffers:
                    buf = buffers[upstream_id]
                    if buf.occupants and can_accept(node_id):
                        out_uid = buf.occupants.pop(0)
                        dispatch_unit_to_target(k, out_uid, route)
                        try_pull_upstream(k, upstream_id, visited)
                elif upstream_id in nodes_by_id and nodes_by_id[upstream_id].kind == "source":
                    if waiting_at_node[upstream_id] and can_accept(node_id):
                        out_uid = waiting_at_node[upstream_id].pop(0)
                        dispatch_unit_to_target(k, out_uid, route)

        def try_start_next_operation(k: EventKernel, station_id: str) -> None:
            st = stations[station_id]
            if (not st.is_busy) and (not st.is_blocked) and waiting_at_node[station_id]:
                next_uid = waiting_at_node[station_id].pop(0)
                op = list(st.operations.values())[0]
                st.start_operation(next_uid, op.id, k.current_time_ns)
                units[next_uid].record_transition(
                    time_ns=k.current_time_ns,
                    state=ProductionUnitState.IN_STATION,
                    location=station_id,
                    station_id=station_id,
                    operation_id=op.id,
                )
                k.schedule(
                    time_ns=k.current_time_ns + op.duration_ns,
                    priority=EventPriority.COMPLETION,
                    event_type="COMPLETE_OPERATION",
                    payload={"unit_id": next_uid, "station_id": station_id, "operation_id": op.id},
                )

        def handle_release(k: EventKernel, event: ScheduledEvent) -> None:
            unit_id = event.payload["unit_id"]
            source_id = event.payload["source_id"]
            unit = units[unit_id]
            unit.record_transition(
                time_ns=k.current_time_ns,
                state=ProductionUnitState.RELEASED,
                location=source_id,
            )

            route = get_available_route(source_id)
            if route and can_accept(route.target_node_id):
                dispatch_unit_to_target(k, unit_id, route)
            else:
                waiting_at_node[source_id].append(unit_id)

        def handle_arrival_at_node(k: EventKernel, event: ScheduledEvent) -> None:
            unit_id = event.payload["unit_id"]
            node_id = event.payload["node_id"]
            node = nodes_by_id[node_id]

            if node.kind == "sink":
                units[unit_id].record_transition(
                    time_ns=k.current_time_ns,
                    state=ProductionUnitState.TERMINAL,
                    location="terminal",
                )
                try_pull_upstream(k, node_id)

            elif node.kind == "buffer":
                buf = buffers[node_id]
                buf.add_unit(unit_id)
                units[unit_id].record_transition(
                    time_ns=k.current_time_ns,
                    state=ProductionUnitState.IN_BUFFER,
                    location=node_id,
                )
                route = get_available_route(node_id)
                if route and can_accept(route.target_node_id):
                    oldest_uid = buf.occupants.pop(0)
                    dispatch_unit_to_target(k, oldest_uid, route)
                    try_pull_upstream(k, node_id)

            elif node.kind == "station":
                st = stations[node_id]
                if (not st.is_busy) and (not st.is_blocked) and (len(waiting_at_node[node_id]) == 0):
                    op = list(st.operations.values())[0]
                    st.start_operation(unit_id, op.id, k.current_time_ns)
                    units[unit_id].record_transition(
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
                        payload={"unit_id": unit_id, "station_id": node_id, "operation_id": op.id},
                    )
                else:
                    waiting_at_node[node_id].append(unit_id)
                    units[unit_id].record_transition(
                        time_ns=k.current_time_ns,
                        state=ProductionUnitState.IN_STATION,
                        location=node_id,
                        station_id=node_id,
                    )

        def handle_complete_operation(k: EventKernel, event: ScheduledEvent) -> None:
            unit_id = event.payload["unit_id"]
            station_id = event.payload["station_id"]
            operation_id = event.payload["operation_id"]
            st = stations[station_id]
            st.complete_operation(operation_id, k.current_time_ns)

            route = get_available_route(station_id)
            downstream_can_accept = route is not None and can_accept(route.target_node_id)

            if downstream_can_accept and route is not None:
                dispatch_unit_to_target(k, unit_id, route)
                try_start_next_operation(k, station_id)
                try_pull_upstream(k, station_id)
            else:
                if len(st.output_buffer) < st.output_capacity:
                    st.output_buffer.append(unit_id)
                    units[unit_id].record_transition(
                        time_ns=k.current_time_ns,
                        state=ProductionUnitState.IN_STATION,
                        location=station_id,
                        station_id=station_id,
                    )
                    try_start_next_operation(k, station_id)
                    try_pull_upstream(k, station_id)
                else:
                    st.start_blocking(unit_id, k.current_time_ns)
                    units[unit_id].record_transition(
                        time_ns=k.current_time_ns,
                        state=ProductionUnitState.BLOCKED,
                        location=station_id,
                        station_id=station_id,
                    )

        kernel.register_handler("RELEASE_UNIT", handle_release)
        kernel.register_handler("ARRIVAL_AT_NODE", handle_arrival_at_node)
        kernel.register_handler("COMPLETE_OPERATION", handle_complete_operation)

        primary_source = next(n for n in mf.nodes if n.kind == "source")
        for u_cfg in cfg.production_units:
            release_ns = max(cfg.episode.start_time_ns, u_cfg.release_time_ns)
            kernel.schedule(
                time_ns=release_ns,
                priority=EventPriority.NEW_WORK,
                event_type="RELEASE_UNIT",
                payload={"unit_id": u_cfg.id, "source_id": primary_source.id},
            )

    else:
        # Minimal single-station path (backward-compatible)
        stations = {
            s_cfg.id: Station(
                id=s_cfg.id,
                operations={
                    op_cfg.id: Operation(id=op_cfg.id, duration_ns=op_cfg.duration_ns)
                    for op_cfg in s_cfg.operations
                },
                output_capacity=s_cfg.output_capacity,
            )
            for s_cfg in cfg.stations
        }
        buffers = {}

        def handle_min_release(k: EventKernel, event: ScheduledEvent) -> None:
            unit_id = event.payload["unit_id"]
            station_id = event.payload["station_id"]
            operation_id = event.payload["operation_id"]
            unit = units[unit_id]
            unit.record_transition(
                time_ns=k.current_time_ns,
                state=ProductionUnitState.RELEASED,
                location=station_id,
            )
            k.schedule(
                time_ns=k.current_time_ns,
                priority=EventPriority.NEW_WORK,
                event_type="START_OPERATION",
                payload={"unit_id": unit_id, "station_id": station_id, "operation_id": operation_id},
            )

        def handle_min_start(k: EventKernel, event: ScheduledEvent) -> None:
            unit_id = event.payload["unit_id"]
            station_id = event.payload["station_id"]
            operation_id = event.payload["operation_id"]
            unit = units[unit_id]
            st = stations[station_id]
            op = st.operations[operation_id]

            st.start_operation(unit_id=unit_id, op_id=operation_id, start_time_ns=k.current_time_ns)
            unit.record_transition(
                time_ns=k.current_time_ns,
                state=ProductionUnitState.IN_STATION,
                location=station_id,
                station_id=station_id,
                operation_id=operation_id,
            )
            k.schedule(
                time_ns=k.current_time_ns + op.duration_ns,
                priority=EventPriority.COMPLETION,
                event_type="COMPLETE_OPERATION",
                payload={"unit_id": unit_id, "station_id": station_id, "operation_id": operation_id},
            )

        def handle_min_complete(k: EventKernel, event: ScheduledEvent) -> None:
            unit_id = event.payload["unit_id"]
            station_id = event.payload["station_id"]
            operation_id = event.payload["operation_id"]
            st = stations[station_id]
            st.complete_operation(op_id=operation_id, completion_time_ns=k.current_time_ns)
            k.schedule(
                time_ns=k.current_time_ns,
                priority=EventPriority.COMPLETION,
                event_type="TERMINATE_UNIT",
                payload={"unit_id": unit_id},
            )

        def handle_min_terminate(k: EventKernel, event: ScheduledEvent) -> None:
            unit_id = event.payload["unit_id"]
            units[unit_id].record_transition(
                time_ns=k.current_time_ns,
                state=ProductionUnitState.TERMINAL,
                location="terminal",
            )

        kernel.register_handler("RELEASE_UNIT", handle_min_release)
        kernel.register_handler("START_OPERATION", handle_min_start)
        kernel.register_handler("COMPLETE_OPERATION", handle_min_complete)
        kernel.register_handler("TERMINATE_UNIT", handle_min_terminate)

        primary_station = cfg.stations[0]
        primary_operation = primary_station.operations[0]

        for u_cfg in cfg.production_units:
            release_ns = max(cfg.episode.start_time_ns, u_cfg.release_time_ns)
            kernel.schedule(
                time_ns=release_ns,
                priority=EventPriority.NEW_WORK,
                event_type="RELEASE_UNIT",
                payload={
                    "unit_id": u_cfg.id,
                    "station_id": primary_station.id,
                    "operation_id": primary_operation.id,
                },
            )

    def is_terminal_condition_met(k: EventKernel) -> bool:
        if cfg.episode.end_condition.type == "all_units_terminal":
            return all(u.state == ProductionUnitState.TERMINAL for u in units.values())
        return False

    kernel.run_until(
        max_time_ns=cfg.episode.end_condition.max_time_ns,
        stop_condition=is_terminal_condition_met,
    )

    all_terminal = is_terminal_condition_met(kernel)
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
        for u in units.values()
    ]

    station_summaries = [
        StationSummary(
            id=s.id,
            operations_completed=s.operations_completed,
            total_busy_time_ns=s.total_busy_time_ns,
            total_blocked_time_ns=s.total_blocked_time_ns,
        )
        for s in stations.values()
    ]

    buffer_summaries = [
        BufferSummary(
            id=b.id,
            capacity=b.capacity,
            peak_occupancy=b.peak_occupancy,
        )
        for b in buffers.values()
    ]

    result_hash = _compute_result_hash(
        status=status,
        seed=cfg.seed,
        simulated_time_ns=kernel.current_time_ns,
        events_processed=kernel.events_processed,
        units=unit_summaries,
        stations=station_summaries,
        buffers=buffer_summaries,
    )

    return EpisodeSummary(
        status=status,
        seed=cfg.seed,
        simulated_time_ns=kernel.current_time_ns,
        events_processed=kernel.events_processed,
        production_units=unit_summaries,
        stations=station_summaries,
        buffers=buffer_summaries,
        result_hash=result_hash,
    )
