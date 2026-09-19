from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


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


@dataclass
class ProductionUnit:
    id: str
    variant: str
    quality_state: str = "nominal"
    state: ProductionUnitState = ProductionUnitState.CREATED
    location: str = "unreleased"
    history: list[HistoryRecord] = field(default_factory=list)

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
        return {
            "id": self.id,
            "variant": self.variant,
            "quality_state": self.quality_state,
            "state": str(self.state),
            "location": self.location,
            "history": [h.to_dict() for h in self.history],
        }

    @classmethod
    def from_snapshot(cls, data: dict[str, Any]) -> ProductionUnit:
        history = [HistoryRecord.from_dict(h) for h in data.get("history", [])]
        return cls(
            id=data["id"],
            variant=data["variant"],
            quality_state=data.get("quality_state", "nominal"),
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

    def is_on_shift(self, time_ns: int) -> bool:
        if not self.shifts:
            return True
        return any(s.start_time_ns <= time_ns < s.end_time_ns for s in self.shifts)

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
            elif self.is_on_break(self.last_state_change_ns):
                self.total_break_time_ns += elapsed
            elif not self.is_on_shift(self.last_state_change_ns):
                self.total_off_shift_time_ns += elapsed
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
            "capacity": self.capacity,
            "active_allocations": list(self.active_allocations),
            "total_busy_time_ns": self.total_busy_time_ns,
            "total_idle_time_ns": self.total_idle_time_ns,
            "total_break_time_ns": self.total_break_time_ns,
            "total_off_shift_time_ns": self.total_off_shift_time_ns,
            "operations_completed": self.operations_completed,
            "last_state_change_ns": self.last_state_change_ns,
        }

    def restore_state(self, state: dict[str, Any]) -> None:
        self.active_allocations = list(state.get("active_allocations", []))
        self.total_busy_time_ns = state.get("total_busy_time_ns", 0)
        self.total_idle_time_ns = state.get("total_idle_time_ns", 0)
        self.total_break_time_ns = state.get("total_break_time_ns", 0)
        self.total_off_shift_time_ns = state.get("total_off_shift_time_ns", 0)
        self.operations_completed = state.get("operations_completed", 0)
        self.last_state_change_ns = state.get("last_state_change_ns", 0)


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


@dataclass
class Operation:
    id: str
    duration_ns: int
    required_machines: list[str] = field(default_factory=list)
    required_workers: list[dict[str, Any]] = field(default_factory=list)
    interruption_policy: str = "resume"


@dataclass
class Station:
    id: str
    operations: dict[str, Operation]
    output_capacity: int = 0
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

    def can_accept(self, reserved: int = 0) -> bool:
        return (
            (not self.is_busy)
            and (not self.is_blocked)
            and (self.current_unit_id is None)
            and reserved == 0
        )

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
