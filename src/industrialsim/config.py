from __future__ import annotations

import re
from typing import Annotated, Any, Literal, Union
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from industrialsim.material_flow import (
    BufferNode,
    MaterialFlowGraph,
    Port,
    PortDirection,
    Route,
    SinkNode,
    SourceNode,
    StationNode,
)


_PART_PATTERN = re.compile(r"(\d+)\s*(ns|us|µs|ms|s|m|min|h|d)?")

_TIME_MULTIPLIERS = {
    "ns": 1,
    "us": 1_000,
    "µs": 1_000,
    "ms": 1_000_000,
    "s": 1_000_000_000,
    "m": 60 * 1_000_000_000,
    "min": 60 * 1_000_000_000,
    "h": 3600 * 1_000_000_000,
    "d": 86400 * 1_000_000_000,
}


def parse_duration_ns(value: int | str) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        if value < 0:
            raise ValueError(f"Duration cannot be negative: {value}")
        return value
    if isinstance(value, str):
        cleaned = value.strip().lower()
        if not cleaned:
            raise ValueError("Invalid duration string: empty string")
        parts = _PART_PATTERN.findall(cleaned)
        if not parts:
            raise ValueError(f"Invalid duration string format: '{value}'")
        reconstructed = "".join(f"{num}{unit}" for num, unit in parts)
        stripped_cleaned = "".join(cleaned.split())
        if reconstructed != stripped_cleaned:
            raise ValueError(f"Invalid duration string format: '{value}'")

        total_ns = 0
        for num_str, unit in parts:
            num = int(num_str)
            multiplier = _TIME_MULTIPLIERS.get(unit or "ns", 1)
            total_ns += num * multiplier
        return total_ns
    raise TypeError(f"Expected int or str for duration, got {type(value).__name__}")


class StrictBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


# Plant location hierarchy
class HallConfig(StrictBaseModel):
    id: str
    name: str


class AreaConfig(StrictBaseModel):
    id: str
    name: str
    halls: list[HallConfig] = Field(default_factory=list)


class PlantConfig(StrictBaseModel):
    id: str
    name: str
    areas: list[AreaConfig] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_plant_hierarchy(self) -> PlantConfig:
        area_ids = [a.id for a in self.areas]
        if len(area_ids) != len(set(area_ids)):
            raise ValueError(f"Duplicate area IDs found in plant: {area_ids}")

        hall_ids: list[str] = []
        for area in self.areas:
            for hall in area.halls:
                hall_ids.append(hall.id)
        if len(hall_ids) != len(set(hall_ids)):
            raise ValueError(f"Duplicate hall IDs found in plant: {hall_ids}")

        return self


# Shifts, Breaks, and Resources
class BreakConfig(StrictBaseModel):
    start_time: int | str
    end_time: int | str | None = None
    duration: int | str | None = None
    start_time_ns: int = 0
    end_time_ns: int = 0
    duration_ns: int = 0

    @model_validator(mode="after")
    def compute_break_times(self) -> BreakConfig:
        start_ns = parse_duration_ns(self.start_time)
        object.__setattr__(self, "start_time_ns", start_ns)
        if self.end_time is not None and self.duration is not None:
            end_ns = parse_duration_ns(self.end_time)
            dur_ns = parse_duration_ns(self.duration)
            if start_ns + dur_ns != end_ns:
                raise ValueError(
                    f"Break end_time ({end_ns}ns) does not match start_time + duration ({start_ns + dur_ns}ns)"
                )
            object.__setattr__(self, "end_time_ns", end_ns)
            object.__setattr__(self, "duration_ns", dur_ns)
        elif self.end_time is not None:
            end_ns = parse_duration_ns(self.end_time)
            if end_ns <= start_ns:
                raise ValueError(f"Break end_time ({end_ns}ns) must be after start_time ({start_ns}ns)")
            object.__setattr__(self, "end_time_ns", end_ns)
            object.__setattr__(self, "duration_ns", end_ns - start_ns)
        elif self.duration is not None:
            dur_ns = parse_duration_ns(self.duration)
            if dur_ns <= 0:
                raise ValueError(f"Break duration must be positive: {dur_ns}")
            object.__setattr__(self, "end_time_ns", start_ns + dur_ns)
            object.__setattr__(self, "duration_ns", dur_ns)
        else:
            raise ValueError("Break must specify either 'end_time' or 'duration'")
        return self


class ShiftConfig(StrictBaseModel):
    id: str
    start_time: int | str
    end_time: int | str
    start_time_ns: int = 0
    end_time_ns: int = 0
    handover_rule: Literal["handover", "run_off", "interrupt"] = "handover"
    breaks: list[BreakConfig] = Field(default_factory=list)

    @model_validator(mode="after")
    def compute_shift_times(self) -> ShiftConfig:
        start_ns = parse_duration_ns(self.start_time)
        end_ns = parse_duration_ns(self.end_time)
        if end_ns <= start_ns:
            raise ValueError(f"Shift '{self.id}' end_time ({end_ns}ns) must be after start_time ({start_ns}ns)")
        object.__setattr__(self, "start_time_ns", start_ns)
        object.__setattr__(self, "end_time_ns", end_ns)

        for b in self.breaks:
            if b.start_time_ns < start_ns or b.end_time_ns > end_ns:
                raise ValueError(
                    f"Break in shift '{self.id}' ({b.start_time_ns}..{b.end_time_ns}ns) is outside shift window ({start_ns}..{end_ns}ns)"
                )
        return self


class MachineModeConfig(StrictBaseModel):
    name: str | None = None
    degradation_multiplier: float = 1.0
    cycle_time_multiplier: float = 1.0
    defect_probability_multiplier: float = 1.0
    hazard_multiplier: float = 1.0

    @model_validator(mode="after")
    def validate_mode(self) -> MachineModeConfig:
        if self.degradation_multiplier < 0.0:
            raise ValueError(f"degradation_multiplier must be >= 0.0, got {self.degradation_multiplier}")
        if self.cycle_time_multiplier <= 0.0:
            raise ValueError(f"cycle_time_multiplier must be > 0.0, got {self.cycle_time_multiplier}")
        if self.defect_probability_multiplier < 0.0:
            raise ValueError(f"defect_probability_multiplier must be >= 0.0, got {self.defect_probability_multiplier}")
        if self.hazard_multiplier < 0.0:
            raise ValueError(f"hazard_multiplier must be >= 0.0, got {self.hazard_multiplier}")
        return self


class DegradationPolicyConfig(StrictBaseModel):
    use_rate_per_s: float = 0.0
    idle_rate_per_s: float = 0.0
    cycle_time_factor: float = 0.0
    defect_probability_factor: float = 0.0
    failure_hazard_rate_per_s: float = 0.0
    hazard_health_factor: float = 0.0
    physical_rates_per_s: dict[str, float] = Field(default_factory=dict)
    physical_idle_rates_per_s: dict[str, float] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_degradation(self) -> DegradationPolicyConfig:
        if self.use_rate_per_s < 0.0:
            raise ValueError(f"use_rate_per_s must be >= 0.0, got {self.use_rate_per_s}")
        if self.idle_rate_per_s < 0.0:
            raise ValueError(f"idle_rate_per_s must be >= 0.0, got {self.idle_rate_per_s}")
        if self.cycle_time_factor < 0.0:
            raise ValueError(f"cycle_time_factor must be >= 0.0, got {self.cycle_time_factor}")
        if self.defect_probability_factor < 0.0:
            raise ValueError(f"defect_probability_factor must be >= 0.0, got {self.defect_probability_factor}")
        if self.failure_hazard_rate_per_s < 0.0:
            raise ValueError(f"failure_hazard_rate_per_s must be >= 0.0, got {self.failure_hazard_rate_per_s}")
        if self.hazard_health_factor < 0.0:
            raise ValueError(f"hazard_health_factor must be >= 0.0, got {self.hazard_health_factor}")
        return self


class MaintenancePolicyConfig(StrictBaseModel):
    trigger: Literal["scheduled", "condition_threshold", "manual", "inspection"] = "condition_threshold"
    health_threshold: float = 0.0
    interval: int | str | None = None
    interval_ns: int = 0
    duration: int | str
    duration_ns: int = 0
    restored_health: float = 1.0
    required_workers: list[WorkerRequirementConfig] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_maintenance(self) -> MaintenancePolicyConfig:
        object.__setattr__(self, "duration_ns", parse_duration_ns(self.duration))
        if self.interval is not None:
            object.__setattr__(self, "interval_ns", parse_duration_ns(self.interval))
        if not (0.0 <= self.health_threshold <= 1.0):
            raise ValueError(f"health_threshold must be in [0.0, 1.0], got {self.health_threshold}")
        if not (0.0 <= self.restored_health <= 1.0):
            raise ValueError(f"restored_health must be in [0.0, 1.0], got {self.restored_health}")
        return self


class MachineInspectionPolicyConfig(StrictBaseModel):
    interval: int | str | None = None
    interval_ns: int = 0
    duration: int | str = "0s"
    duration_ns: int = 0
    restored_health: float | None = None
    health_delta: float = 0.0
    required_workers: list[WorkerRequirementConfig] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_inspection(self) -> MachineInspectionPolicyConfig:
        if self.interval is not None:
            object.__setattr__(self, "interval_ns", parse_duration_ns(self.interval))
        object.__setattr__(self, "duration_ns", parse_duration_ns(self.duration))
        if self.restored_health is not None and not (0.0 <= self.restored_health <= 1.0):
            raise ValueError(f"restored_health must be in [0.0, 1.0], got {self.restored_health}")
        return self


class FailurePolicyConfig(StrictBaseModel):
    mttf: int | str | None = None
    mttf_ns: int = 0
    hazard_rate_per_s: float = 0.0
    health_hazard_factor: float = 0.0
    repair_duration: int | str = "0s"
    repair_duration_ns: int = 0
    mttr: int | str | None = None
    mttr_ns: int = 0
    repaired_health: float = 1.0
    required_workers: list[WorkerRequirementConfig] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_failure(self) -> FailurePolicyConfig:
        if self.mttf is not None:
            object.__setattr__(self, "mttf_ns", parse_duration_ns(self.mttf))
        if self.mttr is not None:
            object.__setattr__(self, "mttr_ns", parse_duration_ns(self.mttr))
        object.__setattr__(self, "repair_duration_ns", parse_duration_ns(self.repair_duration))
        if self.hazard_rate_per_s < 0.0:
            raise ValueError(f"hazard_rate_per_s must be >= 0.0, got {self.hazard_rate_per_s}")
        if self.health_hazard_factor < 0.0:
            raise ValueError(f"health_hazard_factor must be >= 0.0, got {self.health_hazard_factor}")
        if not (0.0 <= self.repaired_health <= 1.0):
            raise ValueError(f"repaired_health must be in [0.0, 1.0], got {self.repaired_health}")
        return self


class PlannedDisruptionConfig(StrictBaseModel):
    id: str | None = None
    start_time: int | str
    start_time_ns: int = 0
    duration: int | str
    duration_ns: int = 0
    repaired_health: float | None = None
    required_workers: list[WorkerRequirementConfig] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_disruption(self) -> PlannedDisruptionConfig:
        object.__setattr__(self, "start_time_ns", parse_duration_ns(self.start_time))
        object.__setattr__(self, "duration_ns", parse_duration_ns(self.duration))
        if self.repaired_health is not None and not (0.0 <= self.repaired_health <= 1.0):
            raise ValueError(f"repaired_health must be in [0.0, 1.0], got {self.repaired_health}")
        return self


class MachineConfig(StrictBaseModel):
    id: str
    name: str | None = None
    capacity: int = 1
    shifts: list[ShiftConfig] = Field(default_factory=list)
    breaks: list[BreakConfig] = Field(default_factory=list)
    initial_health: float = 1.0
    operating_mode: str = "nominal"
    modes: dict[str, MachineModeConfig] = Field(default_factory=dict)
    degradation: DegradationPolicyConfig | None = None
    maintenance: MaintenancePolicyConfig | None = None
    inspection: MachineInspectionPolicyConfig | None = None
    failure: FailurePolicyConfig | None = None
    planned_disruptions: list[PlannedDisruptionConfig] = Field(default_factory=list)
    physical_state: dict[str, float] = Field(default_factory=dict)

    @field_validator("capacity")
    @classmethod
    def validate_capacity(cls, v: int) -> int:
        if v < 1:
            raise ValueError(f"Machine capacity must be >= 1, got {v}")
        return v

    @field_validator("initial_health")
    @classmethod
    def validate_initial_health(cls, v: float) -> float:
        if not (0.0 <= v <= 1.0):
            raise ValueError(f"Machine initial_health must be in [0.0, 1.0], got {v}")
        return v


class WorkerConfig(StrictBaseModel):
    id: str
    name: str | None = None
    kind: Literal["individual", "pool"] = "individual"
    capacity: int = 1
    qualifications: list[str] = Field(default_factory=list)
    shifts: list[ShiftConfig] = Field(default_factory=list)
    breaks: list[BreakConfig] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_worker(self) -> WorkerConfig:
        if self.kind == "individual" and self.capacity != 1:
            raise ValueError(f"Individual worker '{self.id}' must have capacity == 1, got {self.capacity}")
        if self.capacity < 1:
            raise ValueError(f"Worker capacity must be >= 1, got {self.capacity}")
        return self


class WorkerRequirementConfig(StrictBaseModel):
    qualification: str | None = None
    worker_id: str | None = None
    count: int = 1

    @model_validator(mode="after")
    def validate_worker_requirement(self) -> WorkerRequirementConfig:
        if self.qualification is None and self.worker_id is None:
            raise ValueError("Worker requirement must specify at least 'qualification' or 'worker_id'")
        if self.count < 1:
            raise ValueError(f"Worker requirement count must be >= 1, got {self.count}")
        return self


# Vehicles & Logistics
class VehiclePoolConfig(StrictBaseModel):
    id: str
    name: str | None = None
    capabilities: list[str] = Field(default_factory=list)
    speed_multiplier: float = 1.0

    @model_validator(mode="after")
    def validate_pool(self) -> VehiclePoolConfig:
        if self.speed_multiplier <= 0.0:
            raise ValueError(f"Vehicle pool speed_multiplier must be > 0.0, got {self.speed_multiplier}")
        return self


class VehicleConfig(StrictBaseModel):
    id: str
    name: str | None = None
    pool_id: str | None = None
    capabilities: list[str] = Field(default_factory=list)
    initial_location: str
    speed_multiplier: float | None = None

    @model_validator(mode="after")
    def validate_vehicle(self) -> VehicleConfig:
        if self.speed_multiplier is not None and self.speed_multiplier <= 0.0:
            raise ValueError(f"Vehicle speed_multiplier must be > 0.0, got {self.speed_multiplier}")
        return self


# Operations & Stations
class InspectionConfig(StrictBaseModel):
    sensitivity: float = 1.0
    false_positive_rate: float = 0.0
    rework_operation_id: str | None = None
    rework_station_id: str | None = None
    max_reworks: int = 1
    disposition_on_defect: Literal["rework", "scrap"] = "rework"

    @model_validator(mode="after")
    def validate_inspection(self) -> InspectionConfig:
        if not (0.0 <= self.sensitivity <= 1.0):
            raise ValueError(f"Sensitivity must be in [0.0, 1.0], got {self.sensitivity}")
        if not (0.0 <= self.false_positive_rate <= 1.0):
            raise ValueError(f"False positive rate must be in [0.0, 1.0], got {self.false_positive_rate}")
        if self.max_reworks < 0:
            raise ValueError(f"Max reworks cannot be negative: {self.max_reworks}")
        return self


class OperationConfig(StrictBaseModel):
    id: str
    duration: int | str
    duration_ns: int = 0
    required_machines: list[str] = Field(default_factory=list)
    required_workers: list[WorkerRequirementConfig] = Field(default_factory=list)
    interruption_policy: Literal["resume", "restart", "scrap"] = "resume"
    defect_probability: float = 0.0
    defect_name: str | None = None
    target_quality_state: str | None = None
    restores_quality: bool = False
    rework_success_probability: float = 1.0
    inspection: InspectionConfig | None = None

    @model_validator(mode="after")
    def compute_duration_ns(self) -> OperationConfig:
        object.__setattr__(self, "duration_ns", parse_duration_ns(self.duration))
        if not (0.0 <= self.defect_probability <= 1.0):
            raise ValueError(f"defect_probability must be in [0.0, 1.0], got {self.defect_probability}")
        if not (0.0 <= self.rework_success_probability <= 1.0):
            raise ValueError(f"rework_success_probability must be in [0.0, 1.0], got {self.rework_success_probability}")
        return self


class StationConfig(StrictBaseModel):
    id: str
    operations: list[OperationConfig] = Field(min_length=1)
    output_capacity: int = 0

    @field_validator("operations")
    @classmethod
    def validate_unique_operations(cls, v: list[OperationConfig]) -> list[OperationConfig]:
        op_ids = [op.id for op in v]
        if len(op_ids) != len(set(op_ids)):
            raise ValueError(f"Duplicate operation IDs found: {op_ids}")
        return v


# Material Flow Graph
class PortConfig(StrictBaseModel):
    id: str
    port_type: str
    direction: Literal["input", "output"]


class NodeConfig(StrictBaseModel):
    id: str
    kind: Literal["source", "sink", "station", "buffer"]
    hall_id: str | None = None
    capacity: int | None = None
    output_capacity: int = 0
    operations: list[OperationConfig] = Field(default_factory=list)
    input_ports: list[PortConfig] = Field(default_factory=list)
    output_ports: list[PortConfig] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_node(self) -> NodeConfig:
        in_ids = [p.id for p in self.input_ports]
        if len(in_ids) != len(set(in_ids)):
            raise ValueError(f"Duplicate input port IDs on node '{self.id}': {in_ids}")

        out_ids = [p.id for p in self.output_ports]
        if len(out_ids) != len(set(out_ids)):
            raise ValueError(f"Duplicate output port IDs on node '{self.id}': {out_ids}")

        for p in self.input_ports:
            if p.direction != "input":
                raise ValueError(f"Port '{p.id}' on node '{self.id}' is listed as input port but direction is '{p.direction}'")
        for p in self.output_ports:
            if p.direction != "output":
                raise ValueError(f"Port '{p.id}' on node '{self.id}' is listed as output port but direction is '{p.direction}'")

        if self.kind == "source":
            if self.input_ports:
                raise ValueError(f"Source node '{self.id}' cannot have input ports")
        elif self.kind == "sink":
            if self.output_ports:
                raise ValueError(f"Sink node '{self.id}' cannot have output ports")
        elif self.kind == "buffer":
            if self.capacity is None or self.capacity < 1:
                raise ValueError(f"Buffer node '{self.id}' must have capacity >= 1")
        elif self.kind == "station":
            if not self.operations:
                raise ValueError(f"Station node '{self.id}' must have at least one operation")

        return self


class RouteConfig(StrictBaseModel):
    id: str
    source_node_id: str
    source_port_id: str
    target_node_id: str
    target_port_id: str
    transit_time: int | str = 0
    transit_time_ns: int = 0
    capacity: int | None = None
    required_capabilities: list[str] = Field(default_factory=list)
    pool_id: str | None = None

    @model_validator(mode="after")
    def compute_transit_time_ns(self) -> RouteConfig:
        object.__setattr__(self, "transit_time_ns", parse_duration_ns(self.transit_time))
        if self.capacity is not None and self.capacity < 1:
            raise ValueError(f"Route '{self.id}' capacity must be >= 1, got {self.capacity}")
        return self


class MaterialFlowConfig(StrictBaseModel):
    nodes: list[NodeConfig] = Field(min_length=1)
    routes: list[RouteConfig] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_material_flow(self) -> MaterialFlowConfig:
        node_ids = [n.id for n in self.nodes]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError(f"Duplicate node IDs found in material flow: {node_ids}")

        route_ids = [r.id for r in self.routes]
        if len(route_ids) != len(set(route_ids)):
            raise ValueError(f"Duplicate route IDs found in material flow: {route_ids}")

        # Build and validate MaterialFlowGraph
        graph = MaterialFlowGraph()
        for nc in self.nodes:
            in_ports = [
                Port(id=p.id, port_type=p.port_type, direction=PortDirection.INPUT)
                for p in nc.input_ports
            ]
            out_ports = [
                Port(id=p.id, port_type=p.port_type, direction=PortDirection.OUTPUT)
                for p in nc.output_ports
            ]
            if nc.kind == "source":
                graph.add_node(SourceNode(id=nc.id, output_ports=out_ports, hall_id=nc.hall_id))
            elif nc.kind == "sink":
                graph.add_node(SinkNode(id=nc.id, input_ports=in_ports, hall_id=nc.hall_id))
            elif nc.kind == "station":
                graph.add_node(
                    StationNode(
                        id=nc.id,
                        input_ports=in_ports,
                        output_ports=out_ports,
                        output_capacity=nc.output_capacity,
                        hall_id=nc.hall_id,
                    )
                )
            elif nc.kind == "buffer":
                assert nc.capacity is not None
                graph.add_node(
                    BufferNode(
                        id=nc.id,
                        capacity=nc.capacity,
                        input_ports=in_ports,
                        output_ports=out_ports,
                        hall_id=nc.hall_id,
                    )
                )

        for rc in self.routes:
            graph.add_route(
                Route(
                    id=rc.id,
                    source_node_id=rc.source_node_id,
                    source_port_id=rc.source_port_id,
                    target_node_id=rc.target_node_id,
                    target_port_id=rc.target_port_id,
                    transit_time_ns=rc.transit_time_ns,
                    capacity=rc.capacity,
                    required_capabilities=tuple(rc.required_capabilities),
                    pool_id=rc.pool_id,
                )
            )

        errors = graph.validate()
        if errors:
            raise ValueError(f"Material flow graph validation failed: {'; '.join(errors)}")

        return self


class ProductionUnitConfig(StrictBaseModel):
    id: str
    variant: str
    source_id: str | None = None
    release_time: int | str = 0
    release_time_ns: int = 0
    due_date: int | str | None = None
    due_date_ns: int | None = None
    quality_state: str = "nominal"

    @model_validator(mode="after")
    def compute_release_time_ns(self) -> ProductionUnitConfig:
        object.__setattr__(self, "release_time_ns", parse_duration_ns(self.release_time))
        if self.due_date is not None:
            object.__setattr__(self, "due_date_ns", parse_duration_ns(self.due_date))
        return self


class ProductionPlanEntryConfig(StrictBaseModel):
    id: str | None = None
    variant: str
    quantity: int = 1
    release_time: int | str = 0
    release_time_ns: int = 0
    due_date: int | str | None = None
    due_date_ns: int | None = None
    source_id: str | None = None
    quality_state: str = "nominal"

    @model_validator(mode="after")
    def compute_plan_entry_times(self) -> ProductionPlanEntryConfig:
        object.__setattr__(self, "release_time_ns", parse_duration_ns(self.release_time))
        if self.due_date is not None:
            object.__setattr__(self, "due_date_ns", parse_duration_ns(self.due_date))
        if self.quantity < 1:
            raise ValueError(f"Production plan entry quantity must be >= 1, got {self.quantity}")
        return self


class EndConditionConfig(StrictBaseModel):
    type: Literal["all_units_terminal", "max_time"]
    max_time: int | str | None = None
    max_time_ns: int | None = None

    @model_validator(mode="after")
    def compute_max_time_ns(self) -> EndConditionConfig:
        if self.type == "max_time":
            if self.max_time is None:
                raise ValueError("max_time must be provided when type is 'max_time'")
            object.__setattr__(self, "max_time_ns", parse_duration_ns(self.max_time))
        elif self.max_time is not None:
            object.__setattr__(self, "max_time_ns", parse_duration_ns(self.max_time))
        return self


class EpisodeConfig(StrictBaseModel):
    start_time: int | str = 0
    start_time_ns: int = 0
    warm_up_time: int | str = 0
    warm_up_time_ns: int = 0
    end_condition: EndConditionConfig

    @model_validator(mode="after")
    def compute_start_time_ns(self) -> EpisodeConfig:
        object.__setattr__(self, "start_time_ns", parse_duration_ns(self.start_time))
        object.__setattr__(self, "warm_up_time_ns", parse_duration_ns(self.warm_up_time))
        return self


class ProcessPlanStepConfig(StrictBaseModel):
    id: str | None = None
    operation_id: str
    compatible_stations: list[str] = Field(min_length=1)


class ProcessPlanConfig(StrictBaseModel):
    variant: str
    steps: list[ProcessPlanStepConfig] = Field(min_length=1)


class QualityControlBoundsConfig(StrictBaseModel):
    min_inspection_intensity: float = 0.0
    max_inspection_intensity: float = 1.0
    min_sampling_rate: float = 0.0
    max_sampling_rate: float = 1.0
    min_release_threshold: float = 0.0
    max_release_threshold: float = 1.0


class BufferThresholdTriggerConfig(StrictBaseModel):
    id: str
    trigger_type: Literal["buffer_threshold"] = "buffer_threshold"
    buffer_id: str
    threshold: int
    direction: Literal["rising", "falling"] = "rising"
    rearm_threshold: int | None = None
    on_failure: Literal["fallback", "abort"] = "fallback"
    fallback_policy: str = "fifo"

    @model_validator(mode="after")
    def validate_trigger(self) -> BufferThresholdTriggerConfig:
        if self.threshold < 0:
            raise ValueError(f"Trigger '{self.id}' threshold cannot be negative: {self.threshold}")
        if self.rearm_threshold is None:
            if self.direction == "rising":
                object.__setattr__(self, "rearm_threshold", max(0, self.threshold - 1))
            else:
                object.__setattr__(self, "rearm_threshold", self.threshold + 1)
        if self.direction == "rising" and self.rearm_threshold is not None and self.rearm_threshold >= self.threshold:
            raise ValueError(
                f"Trigger '{self.id}' rising rearm_threshold ({self.rearm_threshold}) must be strictly less than threshold ({self.threshold})"
            )
        if self.direction == "falling" and self.rearm_threshold is not None and self.rearm_threshold <= self.threshold:
            raise ValueError(
                f"Trigger '{self.id}' falling rearm_threshold ({self.rearm_threshold}) must be strictly greater than threshold ({self.threshold})"
            )
        return self


class RoutingDecisionTriggerConfig(StrictBaseModel):
    id: str
    trigger_type: Literal["routing_decision"] = "routing_decision"
    node_id: str
    on_failure: Literal["fallback", "abort"] = "fallback"
    fallback_policy: str = "baseline"


class DispatchDecisionTriggerConfig(StrictBaseModel):
    id: str
    trigger_type: Literal["dispatch_decision"] = "dispatch_decision"
    on_failure: Literal["fallback", "abort"] = "fallback"
    fallback_policy: str = "baseline"


class MachineDecisionTriggerConfig(StrictBaseModel):
    id: str
    trigger_type: Literal["machine_decision"] = "machine_decision"
    machine_id: str
    health_threshold: float = 0.3
    rearm_threshold: float | None = None
    on_failure: Literal["fallback", "abort"] = "fallback"
    fallback_policy: str = "baseline"

    @model_validator(mode="after")
    def validate_machine_trigger(self) -> MachineDecisionTriggerConfig:
        if self.rearm_threshold is None:
            object.__setattr__(self, "rearm_threshold", min(1.0, self.health_threshold + 0.2))
        return self


class SafePointTriggerConfig(StrictBaseModel):
    id: str
    trigger_type: Literal["safe_point"] = "safe_point"
    target_id: str
    times_ns: list[int] = Field(default_factory=list)
    interval_ns: int | None = None
    quality_bounds: QualityControlBoundsConfig | None = None
    on_failure: Literal["fallback", "abort"] = "fallback"
    fallback_policy: str = "baseline"


DecisionTriggerConfig = Annotated[
    Union[
        BufferThresholdTriggerConfig,
        RoutingDecisionTriggerConfig,
        DispatchDecisionTriggerConfig,
        MachineDecisionTriggerConfig,
        SafePointTriggerConfig,
    ],
    Field(discriminator="trigger_type"),
]


class RewardComponentConfig(StrictBaseModel):
    name: str
    weight: float = 1.0
    scale: float = 1.0
    offset: float = 0.0
    target: float | None = None
    direction: Literal["maximize", "minimize"] = "maximize"


class RewardPolicyConfig(StrictBaseModel):
    id: str = "default"
    components: list[RewardComponentConfig] = Field(default_factory=list)
    weights: dict[str, float] = Field(default_factory=dict)
    scales: dict[str, float] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _resolve_components(self) -> RewardPolicyConfig:
        existing_names = {c.name for c in self.components}
        new_comps = list(self.components)
        for name, w in self.weights.items():
            if name not in existing_names:
                s = self.scales.get(name, 1.0)
                new_comps.append(RewardComponentConfig(name=name, weight=w, scale=s))
        object.__setattr__(self, "components", new_comps)
        all_weights = {c.name: c.weight for c in self.components}
        object.__setattr__(self, "weights", all_weights)
        return self


class HardConstraintsConfig(StrictBaseModel):
    terminate_on_violation: bool = True
    max_scrap: int | None = None
    max_downtime_ns: int | None = None
    max_lead_time_ns: int | None = None
    enforce_buffer_capacity: bool = True


class BackpressureConfig(StrictBaseModel):
    policy: Literal["thin", "drop_newest", "drop_oldest"] = "thin"
    max_queue_size: int = 100
    thin_factor: int = 2


class TelemetryConfig(StrictBaseModel):
    enabled: bool = True
    sample_interval: int | str | None = None
    sample_interval_ns: int | None = None
    domain_events: list[str] = Field(default_factory=list)
    batch_size: int = 100
    backpressure: BackpressureConfig = Field(default_factory=BackpressureConfig)

    @model_validator(mode="after")
    def compute_sample_interval_ns(self) -> TelemetryConfig:
        if self.sample_interval is not None and self.sample_interval_ns is None:
            object.__setattr__(self, "sample_interval_ns", parse_duration_ns(self.sample_interval))
        return self


class SimulationConfig(StrictBaseModel):
    schema_version: str = "1.0"
    seed: int = 42
    episode: EpisodeConfig
    plant: PlantConfig | None = None
    material_flow: MaterialFlowConfig | None = None
    machines: list[MachineConfig] = Field(default_factory=list)
    workers: list[WorkerConfig] = Field(default_factory=list)
    vehicle_pools: list[VehiclePoolConfig] = Field(default_factory=list)
    vehicles: list[VehicleConfig] = Field(default_factory=list)
    production_units: list[ProductionUnitConfig] = Field(default_factory=list)
    production_plan: list[ProductionPlanEntryConfig] = Field(default_factory=list)
    process_plans: list[ProcessPlanConfig] = Field(default_factory=list)
    stations: list[StationConfig] = Field(default_factory=list)
    reward_policy: RewardPolicyConfig | None = None
    hard_constraints: HardConstraintsConfig | None = None
    telemetry: TelemetryConfig | None = None
    decision_triggers: list[DecisionTriggerConfig] = Field(default_factory=list)

    @field_validator("decision_triggers", mode="before")
    @classmethod
    def _parse_triggers(cls, v: Any) -> Any:
        if isinstance(v, list):
            res = []
            for item in v:
                if isinstance(item, dict) and "trigger_type" not in item:
                    if "buffer_id" in item:
                        item = dict(item, trigger_type="buffer_threshold")
                    elif "machine_id" in item:
                        item = dict(item, trigger_type="machine_decision")
                    elif "node_id" in item:
                        item = dict(item, trigger_type="routing_decision")
                    elif "times_ns" in item:
                        item = dict(item, trigger_type="safe_point")
                    else:
                        item = dict(item, trigger_type="dispatch_decision")
                res.append(item)
            return res
        return v

    @model_validator(mode="after")
    def validate_simulation_config(self) -> SimulationConfig:
        if not self.production_units and not self.production_plan:
            raise ValueError("At least one production unit or production plan entry must be defined")

        if self.production_plan:
            materialized: list[ProductionUnitConfig] = []
            for entry_idx, entry in enumerate(self.production_plan, start=1):
                prefix = entry.id if entry.id else f"{entry.variant}-{entry_idx}"
                for i in range(1, entry.quantity + 1):
                    unit_id = f"{prefix}-{i}"
                    materialized.append(
                        ProductionUnitConfig(
                            id=unit_id,
                            variant=entry.variant,
                            source_id=entry.source_id,
                            release_time=entry.release_time,
                            release_time_ns=entry.release_time_ns,
                            due_date=entry.due_date,
                            due_date_ns=entry.due_date_ns,
                            quality_state=entry.quality_state,
                        )
                    )
            if self.production_units:
                if [u.id for u in self.production_units] != [u.id for u in materialized]:
                    raise ValueError("Cannot specify conflicting 'production_units' and 'production_plan'")
            else:
                object.__setattr__(self, "production_units", materialized)
        unit_ids = [u.id for u in self.production_units]
        if len(unit_ids) != len(set(unit_ids)):
            raise ValueError(f"Duplicate production unit IDs found: {unit_ids}")

        # Validate unique machine and worker IDs
        mach_ids = [m.id for m in self.machines]
        if len(mach_ids) != len(set(mach_ids)):
            raise ValueError(f"Duplicate machine IDs found: {mach_ids}")
        worker_ids = [w.id for w in self.workers]
        if len(worker_ids) != len(set(worker_ids)):
            raise ValueError(f"Duplicate worker IDs found: {worker_ids}")

        pool_ids = [p.id for p in self.vehicle_pools]
        if len(pool_ids) != len(set(pool_ids)):
            raise ValueError(f"Duplicate vehicle pool IDs found: {pool_ids}")

        vehicle_ids = [v.id for v in self.vehicles]
        if len(vehicle_ids) != len(set(vehicle_ids)):
            raise ValueError(f"Duplicate vehicle IDs found: {vehicle_ids}")

        valid_pool_set = set(pool_ids)
        for v in self.vehicles:
            if v.pool_id is not None and v.pool_id not in valid_pool_set:
                raise ValueError(f"Vehicle '{v.id}' references unknown vehicle pool '{v.pool_id}'")

        if self.material_flow is not None:
            valid_node_ids = {node.id for node in self.material_flow.nodes}
            for v in self.vehicles:
                if v.initial_location not in valid_node_ids:
                    raise ValueError(
                        f"Vehicle '{v.id}' references unknown initial_location '{v.initial_location}'"
                    )
            for r in self.material_flow.routes:
                if r.pool_id is not None and r.pool_id not in valid_pool_set:
                    raise ValueError(f"Route '{r.id}' references unknown vehicle pool '{r.pool_id}'")

        valid_mach_set = set(mach_ids)
        valid_worker_set = set(worker_ids)
        valid_qual_set = {q for w in self.workers for q in w.qualifications}

        all_operations: list[OperationConfig] = []
        for s_cfg in self.stations:
            all_operations.extend(s_cfg.operations)
        if self.material_flow is not None:
            for node in self.material_flow.nodes:
                all_operations.extend(node.operations)

        for op in all_operations:
            for m_id in op.required_machines:
                if m_id not in valid_mach_set:
                    raise ValueError(f"Operation '{op.id}' references unknown machine '{m_id}'")
            for req in op.required_workers:
                if req.worker_id is not None and req.worker_id not in valid_worker_set:
                    raise ValueError(f"Operation '{op.id}' references unknown worker '{req.worker_id}'")
                if req.qualification is not None and req.qualification not in valid_qual_set:
                    raise ValueError(f"Operation '{op.id}' references unknown qualification '{req.qualification}'")

        for m in self.machines:
            m_worker_reqs = []
            if m.maintenance:
                m_worker_reqs.extend(m.maintenance.required_workers)
            if m.failure:
                m_worker_reqs.extend(m.failure.required_workers)
            for dis in m.planned_disruptions:
                m_worker_reqs.extend(dis.required_workers)
            for req in m_worker_reqs:
                if req.worker_id is not None and req.worker_id not in valid_worker_set:
                    raise ValueError(f"Machine '{m.id}' references unknown worker '{req.worker_id}'")
                if req.qualification is not None and req.qualification not in valid_qual_set:
                    raise ValueError(f"Machine '{m.id}' references unknown qualification '{req.qualification}'")

        if self.material_flow is None and not self.stations:
            raise ValueError("Either 'material_flow' or 'stations' must be defined")

        if self.stations:
            station_ids = [s.id for s in self.stations]
            if len(station_ids) != len(set(station_ids)):
                raise ValueError(f"Duplicate station IDs found: {station_ids}")

        # Check hall references if both plant and material_flow are defined
        if self.plant is not None and self.material_flow is not None:
            valid_hall_ids = {
                hall.id
                for area in self.plant.areas
                for hall in area.halls
            }
            for node in self.material_flow.nodes:
                if node.hall_id is not None and node.hall_id not in valid_hall_ids:
                    raise ValueError(
                        f"Node '{node.id}' references unknown hall '{node.hall_id}' not found in plant"
                    )

        # Validate production unit sources against material flow
        if self.material_flow is not None:
            source_nodes = [node for node in self.material_flow.nodes if node.kind == "source"]
            source_ids = {node.id for node in source_nodes}
            if not source_ids:
                raise ValueError("Material flow topology must define at least one source node")
            for unit_cfg in self.production_units:
                if unit_cfg.source_id is not None:
                    if unit_cfg.source_id not in source_ids:
                        raise ValueError(
                            f"Production unit '{unit_cfg.id}' references unknown source '{unit_cfg.source_id}'"
                        )
                else:
                    if len(source_ids) > 1:
                        raise ValueError(
                            f"Production unit '{unit_cfg.id}' must specify 'source_id' when material flow contains multiple sources: {sorted(source_ids)}"
                        )

        # Validate process plans
        if self.process_plans:
            plan_variants = [p.variant for p in self.process_plans]
            if len(plan_variants) != len(set(plan_variants)):
                raise ValueError(f"Duplicate process plans for variants: {plan_variants}")

            valid_station_ops: dict[str, set[str]] = {}
            for s_cfg in self.stations:
                valid_station_ops[s_cfg.id] = {op.id for op in s_cfg.operations}
            if self.material_flow is not None:
                for node in self.material_flow.nodes:
                    if node.kind == "station":
                        valid_station_ops[node.id] = {op.id for op in node.operations}

            for plan in self.process_plans:
                for step_idx, step in enumerate(plan.steps):
                    for st_id in step.compatible_stations:
                        if st_id not in valid_station_ops:
                            raise ValueError(
                                f"Process plan for variant '{plan.variant}' step {step_idx + 1} "
                                f"references unknown station '{st_id}'"
                            )
                        if step.operation_id not in valid_station_ops[st_id]:
                            raise ValueError(
                                f"Station '{st_id}' does not provide operation '{step.operation_id}' "
                                f"required by process plan for variant '{plan.variant}'"
                            )

            plan_variant_set = set(plan_variants)
            for u in self.production_units:
                if u.variant not in plan_variant_set:
                    raise ValueError(
                        f"Production unit '{u.id}' variant '{u.variant}' has no matching process plan"
                    )

        # Validate decision triggers
        if self.decision_triggers:
            trigger_ids = [t.id for t in self.decision_triggers]
            if len(trigger_ids) != len(set(trigger_ids)):
                raise ValueError(f"Duplicate decision trigger IDs found: {trigger_ids}")

            if self.material_flow is not None:
                buffer_ids = {node.id for node in self.material_flow.nodes if node.kind == "buffer"}
                for t in self.decision_triggers:
                    if isinstance(t, BufferThresholdTriggerConfig):
                        if t.buffer_id not in buffer_ids:
                            raise ValueError(
                                f"Decision trigger '{t.id}' references unknown buffer '{t.buffer_id}'"
                            )

        return self

