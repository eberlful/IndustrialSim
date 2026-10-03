from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from industrialsim.material_flow import Port


class ProductionUnitState(StrEnum):
    CREATED = "created"
    RELEASED = "released"
    IN_STATION = "in_station"
    IN_BUFFER = "in_buffer"
    IN_TRANSPORT = "in_transport"
    BLOCKED = "blocked"
    TERMINAL = "terminal"


@dataclass(frozen=True)
class HistoryRecord:
    time_ns: int
    state: ProductionUnitState
    location: str
    station_id: str | None = None
    operation_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "time_ns": self.time_ns,
            "state": str(self.state),
            "location": self.location,
        }
        if self.station_id is not None:
            result["station_id"] = self.station_id
        if self.operation_id is not None:
            result["operation_id"] = self.operation_id
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HistoryRecord:
        return cls(
            time_ns=data["time_ns"],
            state=ProductionUnitState(data["state"]),
            location=data["location"],
            station_id=data.get("station_id"),
            operation_id=data.get("operation_id"),
        )


@dataclass(frozen=True)
class QualityFinding:
    time_ns: int
    unit_id: str
    station_id: str
    operation_id: str
    result: str  # "nominal" or "defect_detected"
    disposition: str | None = None  # "pass", "rework", "scrap"

    def to_dict(self) -> dict[str, Any]:
        return {
            "time_ns": self.time_ns,
            "unit_id": self.unit_id,
            "station_id": self.station_id,
            "operation_id": self.operation_id,
            "result": self.result,
            "disposition": self.disposition,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> QualityFinding:
        return cls(
            time_ns=data["time_ns"],
            unit_id=data["unit_id"],
            station_id=data["station_id"],
            operation_id=data["operation_id"],
            result=data["result"],
            disposition=data.get("disposition"),
        )


@dataclass
class ProductionUnit:
    id: str
    variant: str
    quality_state: str = "nominal"
    due_date_ns: int | None = None
    process_step_index: int = 0
    rework_count: int = 0
    is_in_rework: bool = False
    rework_target_station_id: str | None = None
    rework_operation_id: str | None = None
    defects: list[str] = field(default_factory=list)
    findings: list[QualityFinding] = field(default_factory=list)
    state: ProductionUnitState = ProductionUnitState.CREATED
    location: str = "unreleased"
    history: list[HistoryRecord] = field(default_factory=list)

    @property
    def is_defective(self) -> bool:
        return self.quality_state != "nominal" or len(self.defects) > 0

    def alter_quality(self, target_state: str, defect: str | None = None) -> None:
        self.quality_state = target_state
        if defect and defect not in self.defects:
            self.defects.append(defect)

    def restore_quality(self, target_state: str = "nominal") -> None:
        self.quality_state = target_state
        self.defects.clear()

    def record_transition(
        self,
        time_ns: int,
        state: ProductionUnitState,
        location: str,
        station_id: str | None = None,
        operation_id: str | None = None,
    ) -> None:
        self.state = state
        self.location = location
        self.history.append(
            HistoryRecord(
                time_ns=time_ns,
                state=state,
                location=location,
                station_id=station_id,
                operation_id=operation_id,
            )
        )

    def to_snapshot(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "id": self.id,
            "variant": self.variant,
            "quality_state": self.quality_state,
            "process_step_index": self.process_step_index,
            "rework_count": self.rework_count,
            "is_in_rework": self.is_in_rework,
            "rework_target_station_id": self.rework_target_station_id,
            "rework_operation_id": self.rework_operation_id,
            "defects": list(self.defects),
            "findings": [f.to_dict() for f in self.findings],
            "state": str(self.state),
            "location": self.location,
            "history": [h.to_dict() for h in self.history],
        }
        if self.due_date_ns is not None:
            result["due_date_ns"] = self.due_date_ns
        return result

    @classmethod
    def from_snapshot(cls, data: dict[str, Any]) -> ProductionUnit:
        history = [HistoryRecord.from_dict(h) for h in data.get("history", [])]
        findings = [QualityFinding.from_dict(f) for f in data.get("findings", [])]
        return cls(
            id=data["id"],
            variant=data["variant"],
            quality_state=data.get("quality_state", "nominal"),
            due_date_ns=data.get("due_date_ns"),
            process_step_index=data.get("process_step_index", 0),
            rework_count=data.get("rework_count", 0),
            is_in_rework=bool(data.get("is_in_rework", False)),
            rework_target_station_id=data.get("rework_target_station_id"),
            rework_operation_id=data.get("rework_operation_id"),
            defects=list(data.get("defects", [])),
            findings=findings,
            state=ProductionUnitState(data["state"]),
            location=data["location"],
            history=history,
        )

    def to_summary_dict(self) -> dict[str, Any]:
        return self.to_snapshot()


@dataclass(frozen=True)
class Break:
    start_time_ns: int
    end_time_ns: int
    duration_ns: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "start_time_ns": self.start_time_ns,
            "end_time_ns": self.end_time_ns,
            "duration_ns": self.duration_ns,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Break:
        return cls(
            start_time_ns=d["start_time_ns"],
            end_time_ns=d["end_time_ns"],
            duration_ns=d["duration_ns"],
        )


@dataclass(frozen=True)
class Shift:
    id: str
    start_time_ns: int
    end_time_ns: int
    handover_rule: str = "handover"
    breaks: list[Break] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "start_time_ns": self.start_time_ns,
            "end_time_ns": self.end_time_ns,
            "handover_rule": self.handover_rule,
            "breaks": [b.to_dict() for b in self.breaks],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Shift:
        return cls(
            id=d["id"],
            start_time_ns=d["start_time_ns"],
            end_time_ns=d["end_time_ns"],
            handover_rule=d.get("handover_rule", "handover"),
            breaks=[Break.from_dict(b) for b in d.get("breaks", [])],
        )


@dataclass
class Machine:
    id: str
    capacity: int = 1
    shifts: list[Shift] = field(default_factory=list)
    breaks: list[Break] = field(default_factory=list)
    active_allocations: list[dict[str, Any]] = field(default_factory=list)
    total_busy_time_ns: int = 0
    total_idle_time_ns: int = 0
    total_break_time_ns: int = 0
    total_off_shift_time_ns: int = 0
    operations_completed: int = 0
    last_state_change_ns: int = 0
    pending_off_shift: bool = False
    health: float = 1.0
    operating_mode: str = "nominal"
    modes: dict[str, Any] = field(default_factory=dict)
    degradation_policy: dict[str, Any] | None = None
    maintenance_policy: dict[str, Any] | None = None
    inspection_policy: dict[str, Any] | None = None
    failure_policy: dict[str, Any] | None = None
    planned_disruptions: list[dict[str, Any]] = field(default_factory=list)
    physical_state: dict[str, float] = field(default_factory=dict)
    is_failed: bool = False
    is_in_maintenance: bool = False
    total_maintenance_time_ns: int = 0
    total_failed_time_ns: int = 0
    maintenance_count: int = 0
    failure_count: int = 0
    failure_start_ns: int | None = None
    maintenance_start_ns: int | None = None

    def is_on_shift(self, time_ns: int) -> bool:
        if not self.shifts:
            return True
        return any(s.start_time_ns <= time_ns < s.end_time_ns for s in self.shifts)

    def is_on_break(self, time_ns: int) -> bool:
        return any(b.start_time_ns <= time_ns < b.end_time_ns for b in self.breaks)

    def is_available(self, time_ns: int) -> bool:
        if self.pending_off_shift or self.is_failed or self.is_in_maintenance:
            return False
        return self.is_on_shift(time_ns) and not self.is_on_break(time_ns)

    def available_capacity(self, time_ns: int) -> int:
        if not self.is_available(time_ns):
            return 0
        return max(0, self.capacity - len(self.active_allocations))

    def can_allocate(self, count: int = 1, time_ns: int = 0) -> bool:
        return self.available_capacity(time_ns) >= count

    def allocate(self, station_id: str, unit_id: str, op_id: str, time_ns: int) -> None:
        self.update_metrics(time_ns)
        self.active_allocations.append({"station_id": station_id, "unit_id": unit_id, "op_id": op_id})

    def release(self, station_id: str, unit_id: str, op_id: str, time_ns: int, completed: bool = False) -> None:
        self.update_metrics(time_ns)
        for i, alloc in enumerate(self.active_allocations):
            if alloc["station_id"] == station_id and alloc["unit_id"] == unit_id and alloc["op_id"] == op_id:
                self.active_allocations.pop(i)
                if completed:
                    self.operations_completed += 1
                break

    def update_metrics(self, current_time_ns: int) -> None:
        elapsed = current_time_ns - self.last_state_change_ns
        if elapsed > 0:
            dt_s = elapsed / 1_000_000_000.0
            if self.is_failed:
                self.total_failed_time_ns += elapsed
            elif self.is_in_maintenance:
                self.total_maintenance_time_ns += elapsed
            elif len(self.active_allocations) > 0:
                self.total_busy_time_ns += elapsed
                if self.degradation_policy:
                    use_rate = float(self.degradation_policy.get("use_rate_per_s", 0.0))
                    mode_info = self.modes.get(self.operating_mode, {})
                    if isinstance(mode_info, dict):
                        mode_mult = float(mode_info.get("degradation_multiplier", 1.0))
                    else:
                        mode_mult = float(getattr(mode_info, "degradation_multiplier", 1.0))
                    self.health = max(0.0, self.health - dt_s * use_rate * mode_mult)
                    phys_rates = self.degradation_policy.get("physical_rates_per_s", {})
                    for k, rate in phys_rates.items():
                        self.physical_state[k] = self.physical_state.get(k, 0.0) + dt_s * float(rate)
            elif self.is_on_break(self.last_state_change_ns):
                self.total_break_time_ns += elapsed
            elif not self.is_on_shift(self.last_state_change_ns):
                self.total_off_shift_time_ns += elapsed
            else:
                self.total_idle_time_ns += elapsed
                if self.degradation_policy:
                    idle_rate = float(self.degradation_policy.get("idle_rate_per_s", 0.0))
                    self.health = max(0.0, self.health - dt_s * idle_rate)
                    idle_phys_rates = self.degradation_policy.get("physical_idle_rates_per_s", {})
                    for k, rate in idle_phys_rates.items():
                        self.physical_state[k] = self.physical_state.get(k, 0.0) + dt_s * float(rate)
        self.last_state_change_ns = current_time_ns

    def start_failure(self, time_ns: int) -> None:
        self.update_metrics(time_ns)
        self.is_failed = True
        self.failure_count += 1
        self.failure_start_ns = time_ns

    def end_failure(self, time_ns: int, restored_health: float | None = None) -> None:
        self.update_metrics(time_ns)
        self.is_failed = False
        self.failure_start_ns = None
        if restored_health is not None:
            self.health = min(1.0, max(0.0, restored_health))

    def start_maintenance(self, time_ns: int) -> None:
        self.update_metrics(time_ns)
        self.is_in_maintenance = True
        self.maintenance_count += 1
        self.maintenance_start_ns = time_ns

    def end_maintenance(self, time_ns: int, restored_health: float | None = None) -> None:
        self.update_metrics(time_ns)
        self.is_in_maintenance = False
        self.maintenance_start_ns = None
        if restored_health is not None:
            self.health = min(1.0, max(0.0, restored_health))

    def inspect(self, time_ns: int, restored_health: float | None = None, health_delta: float = 0.0) -> None:
        self.update_metrics(time_ns)
        if restored_health is not None:
            self.health = min(1.0, max(0.0, restored_health))
        elif health_delta != 0.0:
            self.health = min(1.0, max(0.0, self.health + health_delta))

    def set_operating_mode(self, mode: str) -> None:
        self.operating_mode = mode

    @property
    def utilization(self) -> float:
        total = self.total_busy_time_ns + self.total_idle_time_ns
        return self.total_busy_time_ns / total if total > 0 else 0.0

    def to_snapshot(self) -> dict[str, Any]:
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
            "pending_off_shift": self.pending_off_shift,
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

    def restore_state(self, state: dict[str, Any]) -> None:
        self.active_allocations = list(state.get("active_allocations", []))
        self.total_busy_time_ns = state.get("total_busy_time_ns", 0)
        self.total_idle_time_ns = state.get("total_idle_time_ns", 0)
        self.total_break_time_ns = state.get("total_break_time_ns", 0)
        self.total_off_shift_time_ns = state.get("total_off_shift_time_ns", 0)
        self.operations_completed = state.get("operations_completed", 0)
        self.last_state_change_ns = state.get("last_state_change_ns", 0)
        self.pending_off_shift = bool(state.get("pending_off_shift", False))
        self.health = float(state.get("health", 1.0))
        self.operating_mode = state.get("operating_mode", "nominal")
        self.physical_state = dict(state.get("physical_state", {}))
        self.is_failed = bool(state.get("is_failed", False))
        self.is_in_maintenance = bool(state.get("is_in_maintenance", False))
        self.total_maintenance_time_ns = state.get("total_maintenance_time_ns", 0)
        self.total_failed_time_ns = state.get("total_failed_time_ns", 0)
        self.maintenance_count = state.get("maintenance_count", 0)
        self.failure_count = state.get("failure_count", 0)
        self.failure_start_ns = state.get("failure_start_ns")
        self.maintenance_start_ns = state.get("maintenance_start_ns")


@dataclass
class Worker:
    id: str
    kind: str = "individual"
    capacity: int = 1
    qualifications: list[str] = field(default_factory=list)
    shifts: list[Shift] = field(default_factory=list)
    breaks: list[Break] = field(default_factory=list)
    active_allocations: list[dict[str, Any]] = field(default_factory=list)
    total_busy_time_ns: int = 0
    total_idle_time_ns: int = 0
    total_break_time_ns: int = 0
    total_off_shift_time_ns: int = 0
    operations_completed: int = 0
    last_state_change_ns: int = 0
    pending_off_shift: bool = False
    assigned_station_id: str | None = None

    def is_on_shift(self, time_ns: int) -> bool:
        if not self.shifts:
            return True
        return any(s.start_time_ns <= time_ns < s.end_time_ns for s in self.shifts)

    def current_shift(self, time_ns: int) -> Shift | None:
        for s in self.shifts:
            if s.start_time_ns <= time_ns < s.end_time_ns:
                return s
        return None

    def is_on_break(self, time_ns: int) -> bool:
        return any(b.start_time_ns <= time_ns < b.end_time_ns for b in self.breaks)

    def is_available(self, time_ns: int) -> bool:
        if self.pending_off_shift:
            return False
        return self.is_on_shift(time_ns) and not self.is_on_break(time_ns)

    def available_capacity(self, time_ns: int) -> int:
        if not self.is_available(time_ns):
            return 0
        return max(0, self.capacity - len(self.active_allocations))

    def can_allocate(self, count: int = 1, time_ns: int = 0) -> bool:
        return self.available_capacity(time_ns) >= count

    def allocate(self, station_id: str, unit_id: str, op_id: str, time_ns: int) -> None:
        self.update_metrics(time_ns)
        self.active_allocations.append({"station_id": station_id, "unit_id": unit_id, "op_id": op_id})

    def release(self, station_id: str, unit_id: str, op_id: str, time_ns: int, completed: bool = False) -> None:
        self.update_metrics(time_ns)
        for i, alloc in enumerate(self.active_allocations):
            if alloc["station_id"] == station_id and alloc["unit_id"] == unit_id and alloc["op_id"] == op_id:
                self.active_allocations.pop(i)
                if completed:
                    self.operations_completed += 1
                break

    def update_metrics(self, current_time_ns: int) -> None:
        elapsed = current_time_ns - self.last_state_change_ns
        if elapsed > 0:
            if len(self.active_allocations) > 0:
                self.total_busy_time_ns += elapsed
            elif not self.is_on_shift(self.last_state_change_ns):
                self.total_off_shift_time_ns += elapsed
            elif self.is_on_break(self.last_state_change_ns):
                self.total_break_time_ns += elapsed
            else:
                self.total_idle_time_ns += elapsed
        self.last_state_change_ns = current_time_ns

    @property
    def utilization(self) -> float:
        total = self.total_busy_time_ns + self.total_idle_time_ns
        return self.total_busy_time_ns / total if total > 0 else 0.0

    def to_snapshot(self) -> dict[str, Any]:
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
            "assigned_station_id": self.assigned_station_id,
            "qualifications": list(self.qualifications),
        }

    def restore_state(self, state: dict[str, Any]) -> None:
        self.active_allocations = list(state.get("active_allocations", []))
        self.total_busy_time_ns = state.get("total_busy_time_ns", 0)
        self.total_idle_time_ns = state.get("total_idle_time_ns", 0)
        self.total_break_time_ns = state.get("total_break_time_ns", 0)
        self.total_off_shift_time_ns = state.get("total_off_shift_time_ns", 0)
        self.operations_completed = state.get("operations_completed", 0)
        self.last_state_change_ns = state.get("last_state_change_ns", 0)
        self.pending_off_shift = bool(state.get("pending_off_shift", False))
        self.assigned_station_id = state.get("assigned_station_id")
        self.qualifications = list(state.get("qualifications", self.qualifications))


@dataclass
class Operation:
    id: str
    duration_ns: int
    required_machines: list[str] = field(default_factory=list)
    required_workers: list[dict[str, Any]] = field(default_factory=list)
    interruption_policy: str = "resume"
    defect_probability: float = 0.0
    defect_name: str | None = None
    target_quality_state: str | None = None
    restores_quality: bool = False
    rework_success_probability: float = 1.0
    inspection: dict[str, Any] | None = None


class TimingPolicy:
    def compute_duration_ns(
        self,
        operation: Operation,
        unit: ProductionUnit | None = None,
        time_ns: int = 0,
        context: Any = None,
    ) -> int:
        raise NotImplementedError


class StandardTimingPolicy(TimingPolicy):
    def compute_duration_ns(
        self,
        operation: Operation,
        unit: ProductionUnit | None = None,
        time_ns: int = 0,
        context: Any = None,
    ) -> int:
        return operation.duration_ns


class ResourceDemandPolicy:
    def get_required_machines(self, operation: Operation, context: Any = None) -> list[str]:
        raise NotImplementedError

    def get_required_workers(self, operation: Operation, context: Any = None) -> list[dict[str, Any]]:
        raise NotImplementedError


class StandardResourceDemandPolicy(ResourceDemandPolicy):
    def get_required_machines(self, operation: Operation, context: Any = None) -> list[str]:
        return list(operation.required_machines)

    def get_required_workers(self, operation: Operation, context: Any = None) -> list[dict[str, Any]]:
        return list(operation.required_workers)


class QualityPolicy:
    def compute_defect(
        self,
        operation: Operation,
        unit: ProductionUnit,
        time_ns: int = 0,
        context: Any = None,
    ) -> tuple[bool, str | None, str | None]:
        raise NotImplementedError

    def compute_rework(
        self,
        operation: Operation,
        unit: ProductionUnit,
        time_ns: int = 0,
        context: Any = None,
    ) -> bool:
        raise NotImplementedError

    def evaluate_inspection(
        self,
        operation: Operation,
        unit: ProductionUnit,
        time_ns: int = 0,
        context: Any = None,
    ) -> QualityFinding | None:
        raise NotImplementedError


class StandardQualityPolicy(QualityPolicy):
    def compute_defect(
        self,
        operation: Operation,
        unit: ProductionUnit,
        time_ns: int = 0,
        context: Any = None,
    ) -> tuple[bool, str | None, str | None]:
        if operation.defect_probability > 0.0 and context is not None:
            random_stream = getattr(context, "random_stream", None)
            if random_stream is not None:
                eff_prob = operation.defect_probability
                defect_roll = random_stream.draw_float("quality", f"{unit.id}:{operation.id}", "defect")
                if defect_roll < eff_prob:
                    defect_name = operation.defect_name or f"defect_{operation.id}"
                    target_state = operation.target_quality_state or defect_name
                    return True, defect_name, target_state
        return False, None, None

    def compute_rework(
        self,
        operation: Operation,
        unit: ProductionUnit,
        time_ns: int = 0,
        context: Any = None,
    ) -> bool:
        if not operation.restores_quality:
            return False
        if operation.rework_success_probability < 1.0 and context is not None:
            random_stream = getattr(context, "random_stream", None)
            if random_stream is not None:
                roll = random_stream.draw_float("quality", f"{unit.id}:{operation.id}", "rework_success")
                return bool(roll < operation.rework_success_probability)
        return True

    def evaluate_inspection(
        self,
        operation: Operation,
        unit: ProductionUnit,
        time_ns: int = 0,
        context: Any = None,
    ) -> QualityFinding | None:
        if not operation.inspection:
            return None
        insp = operation.inspection
        sensitivity = float(insp.get("sensitivity", 1.0))
        fp_rate = float(insp.get("false_positive_rate", 0.0))
        disp_on_defect = insp.get("disposition_on_defect", "scrap")
        max_reworks = int(insp.get("max_reworks", 1))

        is_defect_detected = False
        random_stream = getattr(context, "random_stream", None) if context else None
        if unit.is_defective:
            if random_stream:
                detection_roll = random_stream.draw_float("inspection", f"{unit.id}:{operation.id}", "detection")
                is_defect_detected = detection_roll < sensitivity
            else:
                is_defect_detected = True
        else:
            if random_stream and fp_rate > 0.0:
                fp_roll = random_stream.draw_float("inspection", f"{unit.id}:{operation.id}", "false_positive")
                is_defect_detected = fp_roll < fp_rate

        if is_defect_detected:
            result = "defect_detected"
            if disp_on_defect == "rework" and unit.rework_count >= max_reworks:
                disposition = "scrap"
            else:
                disposition = disp_on_defect
        else:
            result = "nominal"
            disposition = "pass"

        return QualityFinding(
            time_ns=time_ns,
            unit_id=unit.id,
            station_id=getattr(context, "station_id", ""),
            operation_id=operation.id,
            result=result,
            disposition=disposition,
        )


class DegradationPolicy:
    def apply_degradation(
        self,
        machine: Machine,
        dt_s: float,
        operating_mode: str,
        context: Any = None,
    ) -> None:
        raise NotImplementedError


class StandardDegradationPolicy(DegradationPolicy):
    def apply_degradation(
        self,
        machine: Machine,
        dt_s: float,
        operating_mode: str,
        context: Any = None,
    ) -> None:
        if not machine.degradation_policy:
            return
        use_rate = float(machine.degradation_policy.get("use_rate_per_s", 0.0))
        mode_info = machine.modes.get(operating_mode, {})
        if isinstance(mode_info, dict):
            mode_mult = float(mode_info.get("degradation_multiplier", 1.0))
        else:
            mode_mult = float(getattr(mode_info, "degradation_multiplier", 1.0))
        machine.health = max(0.0, machine.health - dt_s * use_rate * mode_mult)
        phys_rates = machine.degradation_policy.get("physical_rates_per_s", {})
        for k, rate in phys_rates.items():
            machine.physical_state[k] = machine.physical_state.get(k, 0.0) + dt_s * float(rate)


class FailurePolicy:
    def evaluate_failure(
        self,
        machine: Machine,
        time_ns: int = 0,
        context: Any = None,
    ) -> bool:
        raise NotImplementedError


class StandardFailurePolicy(FailurePolicy):
    def evaluate_failure(
        self,
        machine: Machine,
        time_ns: int = 0,
        context: Any = None,
    ) -> bool:
        return machine.is_failed


@dataclass
class Station:
    id: str
    operations: dict[str, Operation]
    input_ports: dict[str, Port] = field(default_factory=dict)
    output_ports: dict[str, Port] = field(default_factory=dict)
    output_capacity: int = 0
    type_id: str = "macro_station"
    plugin_id: str | None = None
    plugin_version: str | None = None
    timing_policy: TimingPolicy = field(default_factory=StandardTimingPolicy)
    resource_policy: ResourceDemandPolicy = field(default_factory=StandardResourceDemandPolicy)
    quality_policy: QualityPolicy = field(default_factory=StandardQualityPolicy)
    degradation_policy: DegradationPolicy = field(default_factory=StandardDegradationPolicy)
    failure_policy: FailurePolicy = field(default_factory=StandardFailurePolicy)
    is_busy: bool = False
    is_blocked: bool = False
    current_unit_id: str | None = None
    blocked_unit_id: str | None = None
    output_buffer: list[str] = field(default_factory=list)
    total_busy_time_ns: int = 0
    total_blocked_time_ns: int = 0
    total_waiting_time_ns: int = 0
    operations_completed: int = 0
    interrupted_count: int = 0
    resumed_count: int = 0
    restarted_count: int = 0
    scrapped_count: int = 0
    busy_start_ns: int | None = None
    blocked_start_ns: int | None = None
    waiting_since_ns: int | None = None
    configuration: dict[str, Any] = field(default_factory=dict)
    is_reconfiguring: bool = False

    def get_port(self, port_id: str) -> Port | None:
        return self.input_ports.get(port_id) or self.output_ports.get(port_id)

    def compute_duration_ns(
        self,
        operation: Operation,
        unit: ProductionUnit | None = None,
        time_ns: int = 0,
        context: Any = None,
    ) -> int:
        return self.timing_policy.compute_duration_ns(operation, unit=unit, time_ns=time_ns, context=context)

    def get_required_machines(self, operation: Operation, context: Any = None) -> list[str]:
        return self.resource_policy.get_required_machines(operation, context=context)

    def get_required_workers(self, operation: Operation, context: Any = None) -> list[dict[str, Any]]:
        return self.resource_policy.get_required_workers(operation, context=context)

    def compute_defect(
        self,
        operation: Operation,
        unit: ProductionUnit,
        time_ns: int = 0,
        context: Any = None,
    ) -> tuple[bool, str | None, str | None]:
        return self.quality_policy.compute_defect(operation, unit=unit, time_ns=time_ns, context=context)

    def compute_rework(
        self,
        operation: Operation,
        unit: ProductionUnit,
        time_ns: int = 0,
        context: Any = None,
    ) -> bool:
        return self.quality_policy.compute_rework(operation, unit=unit, time_ns=time_ns, context=context)

    def evaluate_inspection(
        self,
        operation: Operation,
        unit: ProductionUnit,
        time_ns: int = 0,
        context: Any = None,
    ) -> QualityFinding | None:
        return self.quality_policy.evaluate_inspection(operation, unit=unit, time_ns=time_ns, context=context)

    def apply_degradation(
        self,
        machine: Machine,
        dt_s: float,
        operating_mode: str,
        context: Any = None,
    ) -> None:
        self.degradation_policy.apply_degradation(machine, dt_s=dt_s, operating_mode=operating_mode, context=context)

    def evaluate_failure(
        self,
        machine: Machine,
        time_ns: int = 0,
        context: Any = None,
    ) -> bool:
        return self.failure_policy.evaluate_failure(machine, time_ns=time_ns, context=context)

    def can_accept(self, reserved: int = 0) -> bool:
        return (
            (not self.is_busy)
            and (not self.is_blocked)
            and (not self.is_reconfiguring)
            and (self.current_unit_id is None)
            and reserved == 0
        )

    def start_reconfiguration(self, configuration: dict[str, Any], time_ns: int) -> None:
        self.end_waiting(time_ns)
        self.is_busy = True
        self.is_reconfiguring = True
        self.busy_start_ns = time_ns
        self.configuration.update(configuration)

    def complete_reconfiguration(self, completion_time_ns: int) -> None:
        self.is_busy = False
        self.is_reconfiguring = False
        if self.busy_start_ns is not None:
            self.total_busy_time_ns += completion_time_ns - self.busy_start_ns
            self.busy_start_ns = None

    def has_output_space(self) -> bool:
        return len(self.output_buffer) < self.output_capacity

    def enqueue_output_unit(self, unit_id: str) -> None:
        self.output_buffer.append(unit_id)

    def pop_output_unit(self) -> str | None:
        return self.output_buffer.pop(0) if self.output_buffer else None

    def has_output_units(self) -> bool:
        return len(self.output_buffer) > 0

    def start_waiting(self, time_ns: int) -> None:
        if self.waiting_since_ns is None:
            self.waiting_since_ns = time_ns

    def end_waiting(self, time_ns: int) -> None:
        if self.waiting_since_ns is not None:
            self.total_waiting_time_ns += time_ns - self.waiting_since_ns
            self.waiting_since_ns = None

    def start_operation(self, unit_id: str, op_id: str, start_time_ns: int) -> None:
        self.end_waiting(start_time_ns)
        self.is_busy = True
        self.current_unit_id = unit_id
        self.busy_start_ns = start_time_ns

    def complete_operation(self, op_id: str, completion_time_ns: int) -> None:
        self.is_busy = False
        self.current_unit_id = None
        if self.busy_start_ns is not None:
            self.total_busy_time_ns += completion_time_ns - self.busy_start_ns
            self.busy_start_ns = None
        self.operations_completed += 1

    def interrupt_operation(self, time_ns: int) -> None:
        if self.busy_start_ns is not None:
            self.total_busy_time_ns += time_ns - self.busy_start_ns
            self.busy_start_ns = None
        self.is_busy = False
        self.interrupted_count += 1
        self.start_waiting(time_ns)

    def record_resume(self) -> None:
        self.resumed_count += 1

    def record_restart(self) -> None:
        self.restarted_count += 1

    def scrap_operation(self, time_ns: int) -> None:
        if self.busy_start_ns is not None:
            self.total_busy_time_ns += time_ns - self.busy_start_ns
            self.busy_start_ns = None
        self.is_busy = False
        self.current_unit_id = None
        self.interrupted_count += 1
        self.scrapped_count += 1

    def start_blocking(self, unit_id: str, blocked_time_ns: int) -> None:
        self.is_blocked = True
        self.blocked_unit_id = unit_id
        self.blocked_start_ns = blocked_time_ns

    def end_blocking(self, unblocked_time_ns: int) -> None:
        if self.is_blocked:
            if self.blocked_start_ns is not None:
                self.total_blocked_time_ns += unblocked_time_ns - self.blocked_start_ns
                self.blocked_start_ns = None
            self.is_blocked = False
            self.blocked_unit_id = None

    def to_snapshot(self) -> dict[str, Any]:
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
            "is_busy": self.is_busy,
            "is_blocked": self.is_blocked,
            "current_unit_id": self.current_unit_id,
            "blocked_unit_id": self.blocked_unit_id,
            "output_buffer": list(self.output_buffer),
            "busy_start_ns": self.busy_start_ns,
            "blocked_start_ns": self.blocked_start_ns,
            "waiting_since_ns": self.waiting_since_ns,
        }

    def restore_state(self, state: dict[str, Any]) -> None:
        self.operations_completed = state["operations_completed"]
        self.total_busy_time_ns = state["total_busy_time_ns"]
        self.total_blocked_time_ns = state.get("total_blocked_time_ns", 0)
        self.total_waiting_time_ns = state.get("total_waiting_time_ns", 0)
        self.interrupted_count = state.get("interrupted_count", 0)
        self.resumed_count = state.get("resumed_count", 0)
        self.restarted_count = state.get("restarted_count", 0)
        self.scrapped_count = state.get("scrapped_count", 0)
        self.is_busy = state["is_busy"]
        self.is_blocked = state["is_blocked"]
        self.current_unit_id = state.get("current_unit_id")
        self.blocked_unit_id = state.get("blocked_unit_id")
        self.output_buffer = list(state.get("output_buffer", []))
        self.busy_start_ns = state.get("busy_start_ns")
        self.blocked_start_ns = state.get("blocked_start_ns")
        self.waiting_since_ns = state.get("waiting_since_ns")

    def to_summary_dict(self) -> dict[str, Any]:
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


@dataclass
class Buffer:
    id: str
    capacity: int
    occupants: list[str] = field(default_factory=list)
    peak_occupancy: int = 0

    def can_accept(self, reserved: int = 0) -> bool:
        return (len(self.occupants) + reserved) < self.capacity

    def add_unit(self, unit_id: str) -> None:
        if len(self.occupants) >= self.capacity:
            raise RuntimeError(f"Buffer '{self.id}' capacity ({self.capacity}) exceeded!")
        self.occupants.append(unit_id)
        if len(self.occupants) > self.peak_occupancy:
            self.peak_occupancy = len(self.occupants)

    def remove_unit(self, unit_id: str) -> None:
        if unit_id in self.occupants:
            self.occupants.remove(unit_id)

    def pop_unit(self) -> str | None:
        return self.occupants.pop(0) if self.occupants else None

    def has_occupants(self) -> bool:
        return len(self.occupants) > 0

    def to_snapshot(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "capacity": self.capacity,
            "occupants": list(self.occupants),
            "peak_occupancy": self.peak_occupancy,
        }

    def restore_state(self, state: dict[str, Any]) -> None:
        self.occupants = list(state.get("occupants", []))
        self.peak_occupancy = state.get("peak_occupancy", len(self.occupants))

    def to_summary_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "capacity": self.capacity,
            "peak_occupancy": self.peak_occupancy,
        }


class VehicleState(StrEnum):
    IDLE = "idle"
    MOVING_TO_PICKUP = "moving_to_pickup"
    TRANSPORTING = "transporting"


@dataclass
class Vehicle:
    id: str
    initial_location: str
    location: str
    pool_id: str | None = None
    capabilities: list[str] = field(default_factory=list)
    speed_multiplier: float = 1.0
    current_order_id: str | None = None
    current_unit_id: str | None = None
    current_route_id: str | None = None
    state: VehicleState = VehicleState.IDLE
    total_busy_time_ns: int = 0
    total_idle_time_ns: int = 0
    transports_completed: int = 0
    last_state_change_ns: int = 0

    def is_available(self) -> bool:
        return self.state == VehicleState.IDLE and self.current_order_id is None

    def start_repositioning(self, order_id: str, target_node_id: str, time_ns: int) -> None:
        self.update_metrics(time_ns)
        self.current_order_id = order_id
        self.state = VehicleState.MOVING_TO_PICKUP

    def arrive_at_pickup(self, pickup_node_id: str, time_ns: int) -> None:
        self.update_metrics(time_ns)
        self.location = pickup_node_id

    def start_transport(self, order_id: str, unit_id: str, route_id: str, time_ns: int) -> None:
        self.update_metrics(time_ns)
        self.current_order_id = order_id
        self.current_unit_id = unit_id
        self.current_route_id = route_id
        self.state = VehicleState.TRANSPORTING

    def arrive_at_destination(self, destination_node_id: str, time_ns: int) -> None:
        self.update_metrics(time_ns)
        self.location = destination_node_id
        self.current_order_id = None
        self.current_unit_id = None
        self.current_route_id = None
        self.transports_completed += 1
        self.state = VehicleState.IDLE

    def update_metrics(self, current_time_ns: int) -> None:
        elapsed = current_time_ns - self.last_state_change_ns
        if elapsed > 0:
            if self.state != VehicleState.IDLE:
                self.total_busy_time_ns += elapsed
            else:
                self.total_idle_time_ns += elapsed
        self.last_state_change_ns = current_time_ns

    @property
    def utilization(self) -> float:
        total = self.total_busy_time_ns + self.total_idle_time_ns
        return self.total_busy_time_ns / total if total > 0 else 0.0

    def to_snapshot(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "initial_location": self.initial_location,
            "location": self.location,
            "pool_id": self.pool_id,
            "capabilities": list(self.capabilities),
            "current_order_id": self.current_order_id,
            "current_unit_id": self.current_unit_id,
            "current_route_id": self.current_route_id,
            "state": str(self.state),
            "total_busy_time_ns": self.total_busy_time_ns,
            "total_idle_time_ns": self.total_idle_time_ns,
            "transports_completed": self.transports_completed,
            "last_state_change_ns": self.last_state_change_ns,
        }

    def restore_state(self, state: dict[str, Any]) -> None:
        self.location = state["location"]
        self.pool_id = state.get("pool_id", self.pool_id)
        self.capabilities = list(state.get("capabilities", self.capabilities))
        self.current_order_id = state.get("current_order_id")
        self.current_unit_id = state.get("current_unit_id")
        self.current_route_id = state.get("current_route_id")
        self.state = VehicleState(state["state"])
        self.total_busy_time_ns = state.get("total_busy_time_ns", 0)
        self.total_idle_time_ns = state.get("total_idle_time_ns", 0)
        self.transports_completed = state.get("transports_completed", 0)
        self.last_state_change_ns = state.get("last_state_change_ns", 0)


class TransportOrderState(StrEnum):
    PENDING = "pending"
    DISPATCHED = "dispatched"
    IN_TRANSIT = "in_transit"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


@dataclass
class TransportOrder:
    id: str
    unit_id: str
    source_node_id: str
    target_node_id: str
    created_time_ns: int
    assigned_route_id: str | None = None
    assigned_vehicle_id: str | None = None
    state: TransportOrderState = TransportOrderState.PENDING
    dispatched_time_ns: int | None = None
    pickup_time_ns: int | None = None
    completed_time_ns: int | None = None

    def dispatch(self, vehicle_id: str | None, route_id: str, time_ns: int) -> None:
        self.assigned_vehicle_id = vehicle_id
        self.assigned_route_id = route_id
        self.dispatched_time_ns = time_ns
        self.state = TransportOrderState.DISPATCHED

    def pickup(self, time_ns: int) -> None:
        self.pickup_time_ns = time_ns
        self.state = TransportOrderState.IN_TRANSIT

    def complete(self, time_ns: int) -> None:
        self.completed_time_ns = time_ns
        self.state = TransportOrderState.COMPLETED

    def to_snapshot(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "unit_id": self.unit_id,
            "source_node_id": self.source_node_id,
            "target_node_id": self.target_node_id,
            "assigned_route_id": self.assigned_route_id,
            "assigned_vehicle_id": self.assigned_vehicle_id,
            "state": str(self.state),
            "created_time_ns": self.created_time_ns,
            "dispatched_time_ns": self.dispatched_time_ns,
            "pickup_time_ns": self.pickup_time_ns,
            "completed_time_ns": self.completed_time_ns,
        }

    @classmethod
    def from_snapshot(cls, data: dict[str, Any]) -> TransportOrder:
        return cls(
            id=data["id"],
            unit_id=data["unit_id"],
            source_node_id=data["source_node_id"],
            target_node_id=data["target_node_id"],
            assigned_route_id=data.get("assigned_route_id"),
            assigned_vehicle_id=data.get("assigned_vehicle_id"),
            state=TransportOrderState(data["state"]),
            created_time_ns=data["created_time_ns"],
            dispatched_time_ns=data.get("dispatched_time_ns"),
            pickup_time_ns=data.get("pickup_time_ns"),
            completed_time_ns=data.get("completed_time_ns"),
        )
