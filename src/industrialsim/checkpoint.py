from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from industrialsim.config import SimulationConfig


def compute_config_hash(cfg: Any) -> str:
    if hasattr(cfg, "model_dump"):
        raw = cfg.model_dump(mode="json")
    elif isinstance(cfg, dict):
        raw = cfg
    else:
        raise TypeError(f"Expected SimulationConfig or dict, got {type(cfg).__name__}")
    canonical = json.dumps(raw, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def compute_model_hash(cfg: Any) -> str:
    if hasattr(cfg, "model_dump"):
        model_data = {
            "plant": cfg.plant.model_dump(mode="json") if cfg.plant else None,
            "material_flow": cfg.material_flow.model_dump(mode="json") if cfg.material_flow else None,
            "stations": [s.model_dump(mode="json") for s in cfg.stations],
        }
        if getattr(cfg, "machines", None):
            model_data["machines"] = [m.model_dump(mode="json") for m in cfg.machines]
        if getattr(cfg, "workers", None):
            model_data["workers"] = [w.model_dump(mode="json") for w in cfg.workers]
        if getattr(cfg, "vehicle_pools", None):
            model_data["vehicle_pools"] = [p.model_dump(mode="json") for p in cfg.vehicle_pools]
        if getattr(cfg, "vehicles", None):
            model_data["vehicles"] = [v.model_dump(mode="json") for v in cfg.vehicles]
        if getattr(cfg, "process_plans", None):
            model_data["process_plans"] = [p.model_dump(mode="json") for p in cfg.process_plans]
        if getattr(cfg, "decision_triggers", None):
            model_data["decision_triggers"] = [t.model_dump(mode="json") for t in cfg.decision_triggers]
    elif isinstance(cfg, dict):
        model_data = {
            "plant": cfg.get("plant"),
            "material_flow": cfg.get("material_flow"),
            "stations": cfg.get("stations", []),
        }
        if cfg.get("machines"):
            model_data["machines"] = cfg.get("machines")
        if cfg.get("workers"):
            model_data["workers"] = cfg.get("workers")
        if cfg.get("vehicle_pools"):
            model_data["vehicle_pools"] = cfg.get("vehicle_pools")
        if cfg.get("vehicles"):
            model_data["vehicles"] = cfg.get("vehicles")
        if cfg.get("process_plans"):
            model_data["process_plans"] = cfg.get("process_plans")
        if cfg.get("decision_triggers"):
            model_data["decision_triggers"] = cfg.get("decision_triggers")
    else:
        raise TypeError(f"Expected SimulationConfig or dict, got {type(cfg).__name__}")
    canonical = json.dumps(model_data, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class IncompatibleCheckpointError(ValueError):
    """Raised when a checkpoint's compatibility metadata does not match the target runtime or model."""


class InvalidCheckpointError(ValueError):
    """Raised when a checkpoint file or data is corrupted, malformed, or fails integrity checks."""


@dataclass(frozen=True)
class CheckpointEventRecord:
    time_ns: int
    priority: int
    sequence: int
    event_type: str
    payload_version: int = 1
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "time_ns": self.time_ns,
            "priority": self.priority,
            "sequence": self.sequence,
            "event_type": self.event_type,
            "payload_version": self.payload_version,
            "payload": dict(self.payload),
        }

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CheckpointEventRecord:
        return cls(
            time_ns=int(data["time_ns"]),
            priority=int(data["priority"]),
            sequence=int(data["sequence"]),
            event_type=str(data["event_type"]),
            payload_version=int(data.get("payload_version", 1)),
            payload=dict(data.get("payload", {})),
        )


@dataclass(frozen=True)
class ProductionUnitSnapshot:
    id: str
    variant: str
    quality_state: str
    state: str
    location: str
    history: list[dict[str, Any]] = field(default_factory=list)
    due_date_ns: int | None = None
    process_step_index: int = 0
    rework_count: int = 0
    is_in_rework: bool = False
    rework_target_station_id: str | None = None
    rework_operation_id: str | None = None
    defects: list[str] = field(default_factory=list)
    findings: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "id": self.id,
            "variant": self.variant,
            "quality_state": self.quality_state,
            "state": self.state,
            "location": self.location,
            "history": list(self.history),
            "process_step_index": self.process_step_index,
            "rework_count": self.rework_count,
            "is_in_rework": self.is_in_rework,
            "rework_target_station_id": self.rework_target_station_id,
            "rework_operation_id": self.rework_operation_id,
            "defects": list(self.defects),
            "findings": list(self.findings),
        }
        if self.due_date_ns is not None:
            result["due_date_ns"] = self.due_date_ns
        return result

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProductionUnitSnapshot:
        return cls(
            id=str(data["id"]),
            variant=str(data["variant"]),
            quality_state=str(data.get("quality_state", "nominal")),
            state=str(data["state"]),
            location=str(data["location"]),
            history=list(data.get("history", [])),
            due_date_ns=data.get("due_date_ns"),
            process_step_index=int(data.get("process_step_index", 0)),
            rework_count=int(data.get("rework_count", 0)),
            is_in_rework=bool(data.get("is_in_rework", False)),
            rework_target_station_id=data.get("rework_target_station_id"),
            rework_operation_id=data.get("rework_operation_id"),
            defects=list(data.get("defects", [])),
            findings=list(data.get("findings", [])),
        )


@dataclass(frozen=True)
class StationSnapshot:
    id: str
    operations_completed: int
    total_busy_time_ns: int
    total_blocked_time_ns: int = 0
    total_waiting_time_ns: int = 0
    interrupted_count: int = 0
    resumed_count: int = 0
    restarted_count: int = 0
    scrapped_count: int = 0
    is_busy: bool = False
    is_blocked: bool = False
    current_unit_id: str | None = None
    blocked_unit_id: str | None = None
    output_buffer: list[str] = field(default_factory=list)
    busy_start_ns: int | None = None
    blocked_start_ns: int | None = None
    waiting_since_ns: int | None = None
    type_id: str = "macro_station"
    plugin_id: str | None = None
    plugin_version: str | None = None
    parameters: dict[str, Any] = field(default_factory=dict)
    custom_state: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "id": self.id,
            "operations_completed": self.operations_completed,
            "total_busy_time_ns": self.total_busy_time_ns,
            "total_blocked_time_ns": self.total_blocked_time_ns,
            "total_waiting_time_ns": self.total_waiting_time_ns,
            "interrupted_count": self.interrupted_count,
            "resumed_count": self.resumed_count,
            "restarted_count": self.restarted_count,
            "scrapped_count": self.scrapped_count,
            "is_busy": self.is_busy,
            "is_blocked": self.is_blocked,
            "current_unit_id": self.current_unit_id,
            "blocked_unit_id": self.blocked_unit_id,
            "output_buffer": list(self.output_buffer),
            "busy_start_ns": self.busy_start_ns,
            "blocked_start_ns": self.blocked_start_ns,
            "waiting_since_ns": self.waiting_since_ns,
            "type_id": self.type_id,
        }
        if self.plugin_id is not None:
            result["plugin_id"] = self.plugin_id
        if self.plugin_version is not None:
            result["plugin_version"] = self.plugin_version
        if self.parameters:
            result["parameters"] = dict(self.parameters)
        if self.custom_state:
            result["custom_state"] = dict(self.custom_state)
        return result

    def __getitem__(self, key: str) -> Any:
        if hasattr(self, key):
            return getattr(self, key)
        if key in self.custom_state:
            return self.custom_state[key]
        raise KeyError(key)

    def __contains__(self, key: str) -> bool:
        return hasattr(self, key) or key in self.custom_state

    def get(self, key: str, default: Any = None) -> Any:
        if hasattr(self, key):
            return getattr(self, key)
        return self.custom_state.get(key, default)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StationSnapshot:
        custom_state = dict(data.get("custom_state", {}))
        for legacy_k in ("is_micro", "active_stage_index", "stage_start_ns", "active_token", "stages"):
            if legacy_k in data and legacy_k not in custom_state:
                custom_state[legacy_k] = data[legacy_k]

        return cls(
            id=str(data["id"]),
            operations_completed=int(data["operations_completed"]),
            total_busy_time_ns=int(data["total_busy_time_ns"]),
            total_blocked_time_ns=int(data.get("total_blocked_time_ns", 0)),
            total_waiting_time_ns=int(data.get("total_waiting_time_ns", 0)),
            interrupted_count=int(data.get("interrupted_count", 0)),
            resumed_count=int(data.get("resumed_count", 0)),
            restarted_count=int(data.get("restarted_count", 0)),
            scrapped_count=int(data.get("scrapped_count", 0)),
            is_busy=bool(data.get("is_busy", False)),
            is_blocked=bool(data.get("is_blocked", False)),
            current_unit_id=data.get("current_unit_id"),
            blocked_unit_id=data.get("blocked_unit_id"),
            output_buffer=list(data.get("output_buffer", [])),
            busy_start_ns=data.get("busy_start_ns"),
            blocked_start_ns=data.get("blocked_start_ns"),
            waiting_since_ns=data.get("waiting_since_ns"),
            type_id=str(data.get("type_id", "macro_station")),
            plugin_id=data.get("plugin_id"),
            plugin_version=data.get("plugin_version"),
            parameters=dict(data.get("parameters", {})),
            custom_state=custom_state,
        )


@dataclass(frozen=True)
class MachineSnapshot:
    id: str
    capacity: int
    active_allocations: list[dict[str, Any]] = field(default_factory=list)
    total_busy_time_ns: int = 0
    total_idle_time_ns: int = 0
    total_break_time_ns: int = 0
    total_off_shift_time_ns: int = 0
    operations_completed: int = 0
    last_state_change_ns: int = 0
    health: float = 1.0
    operating_mode: str = "nominal"
    physical_state: dict[str, float] = field(default_factory=dict)
    is_failed: bool = False
    is_in_maintenance: bool = False
    total_maintenance_time_ns: int = 0
    total_failed_time_ns: int = 0
    maintenance_count: int = 0
    failure_count: int = 0
    failure_start_ns: int | None = None
    maintenance_start_ns: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "capacity": self.capacity,
            "active_allocations": list(self.active_allocations),
            "total_busy_time_ns": self.total_busy_time_ns,
            "total_idle_time_ns": self.total_idle_time_ns,
            "total_break_time_ns": self.total_break_time_ns,
            "total_off_shift_time_ns": self.total_off_shift_time_ns,
            "operations_completed": self.operations_completed,
            "last_state_change_ns": self.last_state_change_ns,
            "health": self.health,
            "operating_mode": self.operating_mode,
            "physical_state": dict(self.physical_state),
            "is_failed": self.is_failed,
            "is_in_maintenance": self.is_in_maintenance,
            "total_maintenance_time_ns": self.total_maintenance_time_ns,
            "total_failed_time_ns": self.total_failed_time_ns,
            "maintenance_count": self.maintenance_count,
            "failure_count": self.failure_count,
            "failure_start_ns": self.failure_start_ns,
            "maintenance_start_ns": self.maintenance_start_ns,
        }

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MachineSnapshot:
        return cls(
            id=str(data["id"]),
            capacity=int(data["capacity"]),
            active_allocations=list(data.get("active_allocations", [])),
            total_busy_time_ns=int(data.get("total_busy_time_ns", 0)),
            total_idle_time_ns=int(data.get("total_idle_time_ns", 0)),
            total_break_time_ns=int(data.get("total_break_time_ns", 0)),
            total_off_shift_time_ns=int(data.get("total_off_shift_time_ns", 0)),
            operations_completed=int(data.get("operations_completed", 0)),
            last_state_change_ns=int(data.get("last_state_change_ns", 0)),
            health=float(data.get("health", 1.0)),
            operating_mode=str(data.get("operating_mode", "nominal")),
            physical_state=dict(data.get("physical_state", {})),
            is_failed=bool(data.get("is_failed", False)),
            is_in_maintenance=bool(data.get("is_in_maintenance", False)),
            total_maintenance_time_ns=int(data.get("total_maintenance_time_ns", 0)),
            total_failed_time_ns=int(data.get("total_failed_time_ns", 0)),
            maintenance_count=int(data.get("maintenance_count", 0)),
            failure_count=int(data.get("failure_count", 0)),
            failure_start_ns=data.get("failure_start_ns"),
            maintenance_start_ns=data.get("maintenance_start_ns"),
        )


@dataclass(frozen=True)
class WorkerSnapshot:
    id: str
    kind: str
    capacity: int
    active_allocations: list[dict[str, Any]] = field(default_factory=list)
    total_busy_time_ns: int = 0
    total_idle_time_ns: int = 0
    total_break_time_ns: int = 0
    total_off_shift_time_ns: int = 0
    operations_completed: int = 0
    last_state_change_ns: int = 0
    pending_off_shift: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "capacity": self.capacity,
            "active_allocations": list(self.active_allocations),
            "total_busy_time_ns": self.total_busy_time_ns,
            "total_idle_time_ns": self.total_idle_time_ns,
            "total_break_time_ns": self.total_break_time_ns,
            "total_off_shift_time_ns": self.total_off_shift_time_ns,
            "operations_completed": self.operations_completed,
            "last_state_change_ns": self.last_state_change_ns,
            "pending_off_shift": self.pending_off_shift,
        }

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WorkerSnapshot:
        return cls(
            id=str(data["id"]),
            kind=str(data.get("kind", "individual")),
            capacity=int(data.get("capacity", 1)),
            active_allocations=list(data.get("active_allocations", [])),
            total_busy_time_ns=int(data.get("total_busy_time_ns", 0)),
            total_idle_time_ns=int(data.get("total_idle_time_ns", 0)),
            total_break_time_ns=int(data.get("total_break_time_ns", 0)),
            total_off_shift_time_ns=int(data.get("total_off_shift_time_ns", 0)),
            operations_completed=int(data.get("operations_completed", 0)),
            last_state_change_ns=int(data.get("last_state_change_ns", 0)),
            pending_off_shift=bool(data.get("pending_off_shift", False)),
        )


@dataclass(frozen=True)
class BufferSnapshot:
    id: str
    capacity: int
    occupants: list[str] = field(default_factory=list)
    peak_occupancy: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "capacity": self.capacity,
            "occupants": list(self.occupants),
            "peak_occupancy": self.peak_occupancy,
        }

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BufferSnapshot:
        occupants = list(data.get("occupants", []))
        return cls(
            id=str(data["id"]),
            capacity=int(data["capacity"]),
            occupants=occupants,
            peak_occupancy=int(data.get("peak_occupancy", len(occupants))),
        )


@dataclass(frozen=True)
class VehicleSnapshot:
    id: str
    initial_location: str
    location: str
    pool_id: str | None = None
    capabilities: list[str] = field(default_factory=list)
    current_order_id: str | None = None
    current_unit_id: str | None = None
    current_route_id: str | None = None
    state: str = "idle"
    total_busy_time_ns: int = 0
    total_idle_time_ns: int = 0
    transports_completed: int = 0
    last_state_change_ns: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "initial_location": self.initial_location,
            "location": self.location,
            "pool_id": self.pool_id,
            "capabilities": list(self.capabilities),
            "current_order_id": self.current_order_id,
            "current_unit_id": self.current_unit_id,
            "current_route_id": self.current_route_id,
            "state": self.state,
            "total_busy_time_ns": self.total_busy_time_ns,
            "total_idle_time_ns": self.total_idle_time_ns,
            "transports_completed": self.transports_completed,
            "last_state_change_ns": self.last_state_change_ns,
        }

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> VehicleSnapshot:
        return cls(
            id=str(data["id"]),
            initial_location=str(data["initial_location"]),
            location=str(data["location"]),
            pool_id=data.get("pool_id"),
            capabilities=list(data.get("capabilities", [])),
            current_order_id=data.get("current_order_id"),
            current_unit_id=data.get("current_unit_id"),
            current_route_id=data.get("current_route_id"),
            state=str(data.get("state", "idle")),
            total_busy_time_ns=int(data.get("total_busy_time_ns", 0)),
            total_idle_time_ns=int(data.get("total_idle_time_ns", 0)),
            transports_completed=int(data.get("transports_completed", 0)),
            last_state_change_ns=int(data.get("last_state_change_ns", 0)),
        )


@dataclass(frozen=True)
class TransportOrderSnapshot:
    id: str
    unit_id: str
    source_node_id: str
    target_node_id: str
    created_time_ns: int
    assigned_route_id: str | None = None
    assigned_vehicle_id: str | None = None
    state: str = "pending"
    dispatched_time_ns: int | None = None
    pickup_time_ns: int | None = None
    completed_time_ns: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "unit_id": self.unit_id,
            "source_node_id": self.source_node_id,
            "target_node_id": self.target_node_id,
            "created_time_ns": self.created_time_ns,
            "assigned_route_id": self.assigned_route_id,
            "assigned_vehicle_id": self.assigned_vehicle_id,
            "state": self.state,
            "dispatched_time_ns": self.dispatched_time_ns,
            "pickup_time_ns": self.pickup_time_ns,
            "completed_time_ns": self.completed_time_ns,
        }

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TransportOrderSnapshot:
        return cls(
            id=str(data["id"]),
            unit_id=str(data["unit_id"]),
            source_node_id=str(data["source_node_id"]),
            target_node_id=str(data["target_node_id"]),
            created_time_ns=int(data["created_time_ns"]),
            assigned_route_id=data.get("assigned_route_id"),
            assigned_vehicle_id=data.get("assigned_vehicle_id"),
            state=str(data.get("state", "pending")),
            dispatched_time_ns=data.get("dispatched_time_ns"),
            pickup_time_ns=data.get("pickup_time_ns"),
            completed_time_ns=data.get("completed_time_ns"),
        )


@dataclass
class DomainStateSnapshot:
    production_units: dict[str, ProductionUnitSnapshot]
    stations: dict[str, StationSnapshot]
    buffers: dict[str, BufferSnapshot] = field(default_factory=dict)
    machines: dict[str, MachineSnapshot] = field(default_factory=dict)
    workers: dict[str, WorkerSnapshot] = field(default_factory=dict)
    vehicles: dict[str, VehicleSnapshot] = field(default_factory=dict)
    transport_orders: dict[str, TransportOrderSnapshot] = field(default_factory=dict)
    pending_transport_orders: list[str] = field(default_factory=list)
    active_route_occupancy: dict[str, int] = field(default_factory=dict)
    reserved_route_occupancy: dict[str, int] = field(default_factory=dict)
    in_flight_to: dict[str, int] = field(default_factory=dict)
    source_pending_units: dict[str, list[str]] = field(default_factory=dict)
    resource_waiters: list[dict[str, Any]] = field(default_factory=list)
    active_operations: dict[str, dict[str, Any]] = field(default_factory=dict)
    maintenance_waiters: list[dict[str, Any]] = field(default_factory=list)
    active_maintenances: dict[str, dict[str, Any]] = field(default_factory=dict)
    decision_triggers: dict[str, dict[str, Any]] = field(default_factory=dict)
    decision_coordinator: dict[str, Any] = field(default_factory=dict)
    decision_diagnostics: list[dict[str, Any]] = field(default_factory=list)
    decision_batches: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "production_units": {k: v.to_dict() for k, v in self.production_units.items()},
            "stations": {k: v.to_dict() for k, v in self.stations.items()},
            "buffers": {k: v.to_dict() for k, v in self.buffers.items()},
            "machines": {k: v.to_dict() for k, v in self.machines.items()},
            "workers": {k: v.to_dict() for k, v in self.workers.items()},
            "vehicles": {k: v.to_dict() for k, v in self.vehicles.items()},
            "transport_orders": {k: v.to_dict() for k, v in self.transport_orders.items()},
            "pending_transport_orders": list(self.pending_transport_orders),
            "active_route_occupancy": dict(self.active_route_occupancy),
            "reserved_route_occupancy": dict(self.reserved_route_occupancy),
            "in_flight_to": dict(self.in_flight_to),
            "source_pending_units": {k: list(v) for k, v in self.source_pending_units.items()},
            "resource_waiters": list(self.resource_waiters),
            "active_operations": dict(self.active_operations),
            "maintenance_waiters": list(self.maintenance_waiters),
            "active_maintenances": dict(self.active_maintenances),
            "decision_triggers": dict(self.decision_triggers),
            "decision_coordinator": dict(self.decision_coordinator),
            "decision_diagnostics": list(self.decision_diagnostics),
            "decision_batches": list(self.decision_batches),
        }

    def __getitem__(self, key: str) -> Any:
        if key == "production_units":
            return self.production_units
        if key == "stations":
            return self.stations
        if key == "buffers":
            return self.buffers
        if key == "machines":
            return self.machines
        if key == "workers":
            return self.workers
        if key == "vehicles":
            return self.vehicles
        if key == "transport_orders":
            return self.transport_orders
        if key == "pending_transport_orders":
            return self.pending_transport_orders
        if key == "active_route_occupancy":
            return self.active_route_occupancy
        if key == "reserved_route_occupancy":
            return self.reserved_route_occupancy
        if key == "in_flight_to":
            return self.in_flight_to
        if key == "source_pending_units":
            return self.source_pending_units
        if key == "resource_waiters":
            return self.resource_waiters
        if key == "active_operations":
            return self.active_operations
        if key == "maintenance_waiters":
            return self.maintenance_waiters
        if key == "active_maintenances":
            return self.active_maintenances
        if key == "decision_triggers":
            return self.decision_triggers
        if key == "decision_coordinator":
            return self.decision_coordinator
        if key == "decision_diagnostics":
            return self.decision_diagnostics
        if key == "decision_batches":
            return self.decision_batches
        raise KeyError(key)

    def get(self, key: str, default: Any = None) -> Any:
        try:
            return self[key]
        except KeyError:
            return default

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DomainStateSnapshot:
        return cls(
            production_units={
                k: ProductionUnitSnapshot.from_dict(v) if isinstance(v, dict) else v
                for k, v in data.get("production_units", {}).items()
            },
            stations={
                k: StationSnapshot.from_dict(v) if isinstance(v, dict) else v
                for k, v in data.get("stations", {}).items()
            },
            buffers={
                k: BufferSnapshot.from_dict(v) if isinstance(v, dict) else v
                for k, v in data.get("buffers", {}).items()
            },
            machines={
                k: MachineSnapshot.from_dict(v) if isinstance(v, dict) else v
                for k, v in data.get("machines", {}).items()
            },
            workers={
                k: WorkerSnapshot.from_dict(v) if isinstance(v, dict) else v
                for k, v in data.get("workers", {}).items()
            },
            vehicles={
                k: VehicleSnapshot.from_dict(v) if isinstance(v, dict) else v
                for k, v in data.get("vehicles", {}).items()
            },
            transport_orders={
                k: TransportOrderSnapshot.from_dict(v) if isinstance(v, dict) else v
                for k, v in data.get("transport_orders", {}).items()
            },
            pending_transport_orders=list(data.get("pending_transport_orders", [])),
            active_route_occupancy=dict(data.get("active_route_occupancy", {})),
            reserved_route_occupancy=dict(data.get("reserved_route_occupancy", {})),
            in_flight_to=dict(data.get("in_flight_to", {})),
            source_pending_units={
                k: list(v) for k, v in data.get("source_pending_units", {}).items()
            },
            resource_waiters=list(data.get("resource_waiters", [])),
            active_operations=dict(data.get("active_operations", {})),
            maintenance_waiters=list(data.get("maintenance_waiters", [])),
            active_maintenances=dict(data.get("active_maintenances", {})),
            decision_triggers=dict(data.get("decision_triggers", {})),
            decision_coordinator=dict(data.get("decision_coordinator", {})),
            decision_diagnostics=list(data.get("decision_diagnostics", [])),
            decision_batches=list(data.get("decision_batches", [])),
        )


@dataclass
class Checkpoint:
    schema_version: str
    kernel_version: str
    model_hash: str
    config_hash: str
    simulated_time_ns: int
    next_sequence: int
    events_processed: int
    event_queue: list[CheckpointEventRecord]
    domain_state: DomainStateSnapshot
    root_seed: int
    random_occurrence_counters: dict[str, int] = field(default_factory=dict)
    plugin_metadata: dict[str, str] = field(default_factory=dict)
    configuration: dict[str, Any] = field(default_factory=dict)
    checksum: str | None = None

    def __init__(
        self,
        schema_version: str,
        kernel_version: str,
        model_hash: str,
        config_hash: str,
        simulated_time_ns: int,
        events_processed: int,
        event_queue: list[Any],
        domain_state: Any,
        root_seed: int,
        next_sequence: int | None = None,
        sequence_counter: int | None = None,
        random_occurrence_counters: dict[str, int] | None = None,
        plugin_metadata: dict[str, str] | None = None,
        configuration: dict[str, Any] | None = None,
        checksum: str | None = None,
    ) -> None:
        self.schema_version = schema_version
        self.kernel_version = kernel_version
        self.model_hash = model_hash
        self.config_hash = config_hash
        self.simulated_time_ns = simulated_time_ns
        if next_sequence is not None:
            self.next_sequence = next_sequence
        elif sequence_counter is not None:
            self.next_sequence = sequence_counter
        else:
            raise TypeError("Checkpoint requires either 'next_sequence' or 'sequence_counter'")
        self.events_processed = events_processed

        # Wrap event queue records if needed
        self.event_queue = [
            CheckpointEventRecord.from_dict(e) if isinstance(e, dict) else e
            for e in event_queue
        ]

        # Wrap domain state snapshot if needed
        if isinstance(domain_state, DomainStateSnapshot):
            self.domain_state = domain_state
        elif isinstance(domain_state, dict):
            self.domain_state = DomainStateSnapshot.from_dict(domain_state)
        else:
            self.domain_state = domain_state

        self.root_seed = root_seed
        self.random_occurrence_counters = random_occurrence_counters or {}
        self.plugin_metadata = plugin_metadata or {}
        self.configuration = configuration or {}
        self.checksum = checksum

    @property
    def sequence_counter(self) -> int:
        return self.next_sequence

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "kernel_version": self.kernel_version,
            "model_hash": self.model_hash,
            "config_hash": self.config_hash,
            "simulated_time_ns": self.simulated_time_ns,
            "next_sequence": self.next_sequence,
            "sequence_counter": self.next_sequence,
            "events_processed": self.events_processed,
            "event_queue": [e.to_dict() for e in self.event_queue],
            "domain_state": self.domain_state.to_dict(),
            "root_seed": self.root_seed,
            "random_occurrence_counters": dict(self.random_occurrence_counters),
            "plugin_metadata": dict(self.plugin_metadata),
            "configuration": dict(self.configuration),
            "checksum": self.checksum,
        }


@dataclass(frozen=True)
class CheckpointInspection:
    schema_version: str
    kernel_version: str
    model_hash: str
    config_hash: str
    simulated_time_ns: int
    next_sequence: int
    sequence_counter: int
    events_processed: int
    queue_size: int
    root_seed: int
    random_occurrence_counters: dict[str, int]
    plugin_metadata: dict[str, str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "kernel_version": self.kernel_version,
            "model_hash": self.model_hash,
            "config_hash": self.config_hash,
            "simulated_time_ns": self.simulated_time_ns,
            "next_sequence": self.next_sequence,
            "sequence_counter": self.sequence_counter,
            "events_processed": self.events_processed,
            "queue_size": self.queue_size,
            "root_seed": self.root_seed,
            "random_occurrence_counters": self.random_occurrence_counters,
            "plugin_metadata": self.plugin_metadata,
        }



def _compute_checksum(data: dict[str, Any]) -> str:
    """Computes a SHA-256 integrity checksum over the canonical payload excluding 'checksum'."""
    payload_copy = {k: v for k, v in data.items() if k != "checksum"}
    canonical = json.dumps(payload_copy, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def serialize_checkpoint(checkpoint: Checkpoint) -> str:
    data = checkpoint.to_dict()
    data["checksum"] = _compute_checksum(data)
    return json.dumps(data, indent=2, sort_keys=True)


def deserialize_checkpoint(raw: str | dict[str, Any]) -> Checkpoint:
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
        except Exception as e:
            raise InvalidCheckpointError(f"Checkpoint JSON decoding failed: {e}") from e
    elif isinstance(raw, dict):
        data = dict(raw)
    else:
        raise InvalidCheckpointError(f"Unsupported checkpoint input type: {type(raw).__name__}")

    if not isinstance(data, dict):
        raise InvalidCheckpointError("Checkpoint root structure must be a JSON object mapping")

    required_fields = [
        "schema_version",
        "kernel_version",
        "model_hash",
        "config_hash",
        "simulated_time_ns",
        "events_processed",
        "event_queue",
        "domain_state",
        "root_seed",
    ]
    missing = [f for f in required_fields if f not in data]
    if "next_sequence" not in data and "sequence_counter" not in data:
        missing.append("next_sequence")
    if missing:
        raise InvalidCheckpointError(f"Checkpoint data missing required fields: {missing}")

    raw_seq = data.get("next_sequence")
    if raw_seq is None:
        raw_seq = data.get("sequence_counter", 0)
    seq_val = int(raw_seq)

    # Checksum verification
    recorded_checksum = data.get("checksum")
    if recorded_checksum is not None:
        computed_checksum = _compute_checksum(data)
        if recorded_checksum != computed_checksum:
            raise InvalidCheckpointError(
                f"Checkpoint integrity check failed: payload checksum mismatch (expected {recorded_checksum}, got {computed_checksum})"
            )

    return Checkpoint(
        schema_version=str(data["schema_version"]),
        kernel_version=str(data["kernel_version"]),
        model_hash=str(data["model_hash"]),
        config_hash=str(data["config_hash"]),
        simulated_time_ns=int(data["simulated_time_ns"]),
        next_sequence=seq_val,
        events_processed=int(data["events_processed"]),
        event_queue=list(data["event_queue"]),
        domain_state=dict(data["domain_state"]),
        root_seed=int(data["root_seed"]),
        random_occurrence_counters=dict(data.get("random_occurrence_counters", {})),
        plugin_metadata=dict(data.get("plugin_metadata", {})),
        configuration=dict(data.get("configuration", {})),
        checksum=recorded_checksum,
    )



def save_checkpoint(checkpoint: Checkpoint, path: str | Path) -> None:
    target_path = Path(path)
    target_path.parent.mkdir(parents=True, exist_ok=True)

    serialized = serialize_checkpoint(checkpoint)

    # Atomic write pattern: write to temporary file in the same directory, flush, sync, and replace.
    temp_file = tempfile.NamedTemporaryFile(
        dir=target_path.parent,
        prefix=f".{target_path.stem}_",
        suffix=".tmp",
        mode="w",
        encoding="utf-8",
        delete=False,
    )
    temp_path = Path(temp_file.name)
    try:
        temp_file.write(serialized)
        temp_file.flush()
        os.fsync(temp_file.fileno())
        temp_file.close()
        os.replace(temp_path, target_path)
    except Exception:
        if temp_path.exists():
            temp_path.unlink()
        raise


def load_checkpoint(path: str | Path) -> Checkpoint:
    file_path = Path(path)
    if not file_path.is_file():
        raise InvalidCheckpointError(f"Checkpoint file not found: {file_path}")

    try:
        content = file_path.read_text(encoding="utf-8")
    except Exception as e:
        raise InvalidCheckpointError(f"Failed to read checkpoint file '{file_path}': {e}") from e

    return deserialize_checkpoint(content)


def inspect_checkpoint(source: str | Path | dict[str, Any] | Checkpoint) -> CheckpointInspection:
    if isinstance(source, Checkpoint):
        cp = source
    elif isinstance(source, Path):
        cp = load_checkpoint(source)
    elif isinstance(source, str) and not source.strip().startswith("{"):
        cp = load_checkpoint(source)
    elif isinstance(source, (str, dict)):
        cp = deserialize_checkpoint(source)
    else:
        raise InvalidCheckpointError(f"Unsupported checkpoint inspection source: {type(source).__name__}")

    return CheckpointInspection(
        schema_version=cp.schema_version,
        kernel_version=cp.kernel_version,
        model_hash=cp.model_hash,
        config_hash=cp.config_hash,
        simulated_time_ns=cp.simulated_time_ns,
        next_sequence=cp.next_sequence,
        sequence_counter=cp.sequence_counter,
        events_processed=cp.events_processed,
        queue_size=len(cp.event_queue),
        root_seed=cp.root_seed,
        random_occurrence_counters=cp.random_occurrence_counters,
        plugin_metadata=cp.plugin_metadata,
    )
