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
    history: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "variant": self.variant,
            "quality_state": self.quality_state,
            "state": self.state,
            "history": self.history,
        }


@dataclass(frozen=True)
class StationSummary:
    id: str
    operations_completed: int
    total_busy_time_ns: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "operations_completed": self.operations_completed,
            "total_busy_time_ns": self.total_busy_time_ns,
        }


@dataclass(frozen=True)
class EpisodeSummary:
    status: str
    simulated_time_ns: int
    events_processed: int
    production_units: list[ProductionUnitSummary]
    stations: list[StationSummary]
    result_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "simulated_time_ns": self.simulated_time_ns,
            "events_processed": self.events_processed,
            "production_units": [u.to_dict() for u in self.production_units],
            "stations": [s.to_dict() for s in self.stations],
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


def _compute_result_hash(
    status: str,
    simulated_time_ns: int,
    events_processed: int,
    units: list[ProductionUnitSummary],
    stations: list[StationSummary],
) -> str:
    data = {
        "status": status,
        "simulated_time_ns": simulated_time_ns,
        "events_processed": events_processed,
        "production_units": [u.to_dict() for u in units],
        "stations": [s.to_dict() for s in stations],
    }
    canonical_json = json.dumps(data, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


def run_episode(source: str | Path | dict[str, Any]) -> EpisodeSummary:
    validation = validate_config(source)
    if not validation.is_valid or validation.config is None:
        raise ValueError(f"Invalid configuration: {'; '.join(validation.errors)}")

    cfg = validation.config

    # Domain objects
    units: dict[str, ProductionUnit] = {
        u_cfg.id: ProductionUnit(id=u_cfg.id, variant=u_cfg.variant)
        for u_cfg in cfg.production_units
    }

    stations: dict[str, Station] = {
        s_cfg.id: Station(
            id=s_cfg.id,
            operations={
                op_cfg.id: Operation(id=op_cfg.id, duration_ns=op_cfg.duration_ns)
                for op_cfg in s_cfg.operations
            },
        )
        for s_cfg in cfg.stations
    }

    kernel = EventKernel(initial_time_ns=cfg.episode.start_time_ns)

    # Handlers for domain events
    def handle_release(k: EventKernel, event: ScheduledEvent) -> None:
        unit_id = event.payload["unit_id"]
        station_id = event.payload["station_id"]
        operation_id = event.payload["operation_id"]
        unit = units[unit_id]
        unit.record_transition(time_ns=k.current_time_ns, state=ProductionUnitState.RELEASED)

        # In this minimal slice, immediately schedule START_OPERATION
        k.schedule(
            time_ns=k.current_time_ns,
            priority=EventPriority.NEW_WORK,
            event_type="START_OPERATION",
            payload={"unit_id": unit_id, "station_id": station_id, "operation_id": operation_id},
        )

    def handle_start_operation(k: EventKernel, event: ScheduledEvent) -> None:
        unit_id = event.payload["unit_id"]
        station_id = event.payload["station_id"]
        operation_id = event.payload["operation_id"]
        unit = units[unit_id]
        station = stations[station_id]
        op = station.operations[operation_id]

        station.start_operation(unit_id=unit_id, op_id=operation_id, start_time_ns=k.current_time_ns)
        unit.record_transition(
            time_ns=k.current_time_ns,
            state=ProductionUnitState.IN_STATION,
            station_id=station_id,
            operation_id=operation_id,
        )

        k.schedule(
            time_ns=k.current_time_ns + op.duration_ns,
            priority=EventPriority.COMPLETION,
            event_type="COMPLETE_OPERATION",
            payload={"unit_id": unit_id, "station_id": station_id, "operation_id": operation_id},
        )

    def handle_complete_operation(k: EventKernel, event: ScheduledEvent) -> None:
        unit_id = event.payload["unit_id"]
        station_id = event.payload["station_id"]
        operation_id = event.payload["operation_id"]
        unit = units[unit_id]
        station = stations[station_id]

        station.complete_operation(op_id=operation_id, completion_time_ns=k.current_time_ns)
        unit.record_transition(
            time_ns=k.current_time_ns,
            state="operation_completed",
            station_id=station_id,
            operation_id=operation_id,
        )

        k.schedule(
            time_ns=k.current_time_ns,
            priority=EventPriority.COMPLETION,
            event_type="TERMINATE_UNIT",
            payload={"unit_id": unit_id},
        )

    def handle_terminate_unit(k: EventKernel, event: ScheduledEvent) -> None:
        unit_id = event.payload["unit_id"]
        unit = units[unit_id]
        unit.record_transition(time_ns=k.current_time_ns, state=ProductionUnitState.TERMINAL)

    kernel.register_handler("RELEASE_UNIT", handle_release)
    kernel.register_handler("START_OPERATION", handle_start_operation)
    kernel.register_handler("COMPLETE_OPERATION", handle_complete_operation)
    kernel.register_handler("TERMINATE_UNIT", handle_terminate_unit)

    # Initial scheduling
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

    all_terminal = all(u.state == ProductionUnitState.TERMINAL for u in units.values())
    status = "completed" if all_terminal else "incomplete"

    unit_summaries = [
        ProductionUnitSummary(
            id=u.id,
            variant=u.variant,
            quality_state=u.quality_state,
            state=u.state,
            history=[h.to_dict() for h in u.history],
        )
        for u in units.values()
    ]

    station_summaries = [
        StationSummary(
            id=s.id,
            operations_completed=s.operations_completed,
            total_busy_time_ns=s.total_busy_time_ns,
        )
        for s in stations.values()
    ]

    result_hash = _compute_result_hash(
        status=status,
        simulated_time_ns=kernel.current_time_ns,
        events_processed=kernel.events_processed,
        units=unit_summaries,
        stations=station_summaries,
    )

    return EpisodeSummary(
        status=status,
        simulated_time_ns=kernel.current_time_ns,
        events_processed=kernel.events_processed,
        production_units=unit_summaries,
        stations=station_summaries,
        result_hash=result_hash,
    )
