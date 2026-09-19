from __future__ import annotations

import re
from typing import Any, Literal
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


class MachineConfig(StrictBaseModel):
    id: str
    name: str | None = None
    capacity: int = 1
    shifts: list[ShiftConfig] = Field(default_factory=list)
    breaks: list[BreakConfig] = Field(default_factory=list)

    @field_validator("capacity")
    @classmethod
    def validate_capacity(cls, v: int) -> int:
        if v < 1:
            raise ValueError(f"Machine capacity must be >= 1, got {v}")
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


# Operations & Stations
class OperationConfig(StrictBaseModel):
    id: str
    duration: int | str
    duration_ns: int = 0
    required_machines: list[str] = Field(default_factory=list)
    required_workers: list[WorkerRequirementConfig] = Field(default_factory=list)
    interruption_policy: Literal["resume", "restart", "scrap"] = "resume"

    @model_validator(mode="after")
    def compute_duration_ns(self) -> OperationConfig:
        object.__setattr__(self, "duration_ns", parse_duration_ns(self.duration))
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

    @model_validator(mode="after")
    def compute_transit_time_ns(self) -> RouteConfig:
        object.__setattr__(self, "transit_time_ns", parse_duration_ns(self.transit_time))
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

    @model_validator(mode="after")
    def compute_release_time_ns(self) -> ProductionUnitConfig:
        object.__setattr__(self, "release_time_ns", parse_duration_ns(self.release_time))
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
    end_condition: EndConditionConfig

    @model_validator(mode="after")
    def compute_start_time_ns(self) -> EpisodeConfig:
        object.__setattr__(self, "start_time_ns", parse_duration_ns(self.start_time))
        return self


class SimulationConfig(StrictBaseModel):
    schema_version: str = "1.0"
    seed: int = 42
    episode: EpisodeConfig
    plant: PlantConfig | None = None
    material_flow: MaterialFlowConfig | None = None
    machines: list[MachineConfig] = Field(default_factory=list)
    workers: list[WorkerConfig] = Field(default_factory=list)
    production_units: list[ProductionUnitConfig] = Field(min_length=1)
    stations: list[StationConfig] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_simulation_config(self) -> SimulationConfig:
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

        return self
