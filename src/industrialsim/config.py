from __future__ import annotations

import re
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


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

    @field_validator("operations")
    @classmethod
    def validate_unique_operations(cls, v: list[OperationConfig]) -> list[OperationConfig]:
        op_ids = [op.id for op in v]
        if len(op_ids) != len(set(op_ids)):
            raise ValueError(f"Duplicate operation IDs found: {op_ids}")
        return v


class ProductionUnitConfig(StrictBaseModel):
    id: str
    variant: str
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
    production_units: list[ProductionUnitConfig] = Field(min_length=1)
    stations: list[StationConfig] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_ids(self) -> SimulationConfig:
        unit_ids = [u.id for u in self.production_units]
        if len(unit_ids) != len(set(unit_ids)):
            raise ValueError(f"Duplicate production unit IDs found: {unit_ids}")

        station_ids = [s.id for s in self.stations]
        if len(station_ids) != len(set(station_ids)):
            raise ValueError(f"Duplicate station IDs found: {station_ids}")

        return self

