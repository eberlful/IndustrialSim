from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class ProductionUnitState(StrEnum):
    CREATED = "created"
    RELEASED = "released"
    IN_STATION = "in_station"
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

    def to_summary_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "variant": self.variant,
            "quality_state": self.quality_state,
            "state": str(self.state),
            "location": self.location,
            "history": [h.to_dict() for h in self.history],
        }


@dataclass
class Operation:
    id: str
    duration_ns: int


@dataclass
class Station:
    id: str
    operations: dict[str, Operation]
    is_busy: bool = False
    current_unit_id: str | None = None
    total_busy_time_ns: int = 0
    operations_completed: int = 0
    busy_start_ns: int | None = None

    def start_operation(self, unit_id: str, op_id: str, start_time_ns: int) -> None:
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

    def to_summary_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "operations_completed": self.operations_completed,
            "total_busy_time_ns": self.total_busy_time_ns,
        }
