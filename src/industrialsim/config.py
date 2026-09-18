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


_DURATION_PATTERN = re.compile(r"^(\d+)\s*(ns|us|µs|ms|s|m|min|h|d)?$")

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
        match = _DURATION_PATTERN.match(cleaned)
        if not match:
            raise ValueError(f"Invalid duration string format: '{value}'")
        num_str, unit = match.groups()
        num = int(num_str)
        multiplier = _TIME_MULTIPLIERS.get(unit or "ns", 1)
        return num * multiplier
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


# Operations & Stations
class OperationConfig(StrictBaseModel):
    id: str
    duration: int | str
    duration_ns: int = 0

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
    production_units: list[ProductionUnitConfig] = Field(min_length=1)
    stations: list[StationConfig] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_simulation_config(self) -> SimulationConfig:
        unit_ids = [u.id for u in self.production_units]
        if len(unit_ids) != len(set(unit_ids)):
            raise ValueError(f"Duplicate production unit IDs found: {unit_ids}")

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

        return self
